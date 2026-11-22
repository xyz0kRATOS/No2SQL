"""
Google Gemini LLM Integration for No2SQL.
Uses gemini-3.5-flash-lite by default (fastest, most reliable for this API key tier).
Automatically discovers the best working model by actually testing generate_content.
The API key is loaded from .env on the backend and never exposed to the UI.
"""

import hashlib
import json
import logging
import re
import time
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError

from ..config import settings
from ..schemas.models import LLMOutputModel

logger = logging.getLogger("no2sql.llm")

# Ordered list of candidate models to try if the preferred one fails.
# These are models confirmed available for Antigravity API keys.
FLASH_MODEL_CANDIDATES = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-3.1-flash-lite",
]


def clean_json_text(text: str) -> str:
    """Removes markdown code fences if present."""
    if not text:
        return ""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


class GeminiService:
    def __init__(self):
        self._cached_status: Optional[Dict[str, Any]] = None
        self._status_timestamp: float = 0.0
        self._suggestions_cache: Dict[str, List[str]] = {}

    def get_client(self) -> genai.Client:
        key = settings.GEMINI_API_KEY
        if not key:
            raise ValueError(
                "Gemini API key is missing. Please ensure GEMINI_API_KEY is configured in your .env file."
            )
        return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=25000))

    def resolve_model(self, client: genai.Client) -> str:
        """
        Returns a working model by actually probing generate_content (not just models.get).
        Tries the preferred model first, then falls through the candidate list.
        Result is cached in settings.RESOLVED_LLM_MODEL.
        """
        if settings.RESOLVED_LLM_MODEL:
            return settings.RESOLVED_LLM_MODEL

        preferred = settings.LLM_MODEL or "gemini-3.5-flash-lite"

        # Build ordered probe list: preferred first, then remaining candidates
        probe_order = [preferred] + [m for m in FLASH_MODEL_CANDIDATES if m != preferred]

        for model in probe_order:
            try:
                logger.info(f"Probing model: {model}")
                resp = client.models.generate_content(
                    model=model,
                    contents='{"probe": true}',
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                )
                if resp.text:
                    logger.info(f"Model resolved to: {model}")
                    settings.RESOLVED_LLM_MODEL = model
                    return model
            except APIError as e:
                code = getattr(e, "code", 0)
                logger.warning(f"Model {model} probe failed ({code}): {str(e)[:120]}")
                if code == 404:
                    continue  # model not available for this key
                if code in (429, 503):
                    # Rate limited — model exists but is overloaded; still prefer it
                    logger.info(f"Model {model} exists but is rate-limited ({code}); selecting it anyway.")
                    settings.RESOLVED_LLM_MODEL = model
                    return model
                continue
            except Exception as ex:
                logger.warning(f"Model {model} probe error: {str(ex)[:120]}")
                continue

        # If all probes timed out or failed, fall back to preferred and let generate() handle errors
        logger.warning(f"No model probe succeeded; defaulting to {preferred}")
        settings.RESOLVED_LLM_MODEL = preferred
        return preferred

    def check_connection_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Verifies Gemini API readiness by doing a real lightweight generate_content call.
        Cached for 60 seconds unless force_refresh is True.
        Returns: { "status": "connected" | "missing_key" | "error", "model": str, "message": str }
        """
        now = time.time()
        if not force_refresh and self._cached_status and (now - self._status_timestamp < 60.0):
            return self._cached_status

        if not settings.GEMINI_API_KEY:
            status_obj = {
                "status": "missing_key",
                "model": settings.LLM_MODEL or "gemini-3.5-flash-lite",
                "message": "Gemini API key is missing. Add GEMINI_API_KEY to your .env file.",
            }
            self._cached_status = status_obj
            self._status_timestamp = now
            return status_obj

        try:
            client = self.get_client()
            # Reset cached model so resolve_model re-probes (on force_refresh)
            if force_refresh:
                settings.RESOLVED_LLM_MODEL = ""

            active_model = self.resolve_model(client)

            status_obj = {
                "status": "connected",
                "model": active_model,
                "message": f"Connected to Google Gemini ({active_model}).",
            }
        except APIError as api_err:
            msg = str(api_err)
            code = getattr(api_err, "code", 0)
            if code in (401, 403) or "API_KEY_INVALID" in msg:
                friendly_msg = "Gemini API key is invalid or unauthorized. Please check GEMINI_API_KEY in .env."
            elif code == 429 or "RESOURCE_EXHAUSTED" in msg:
                friendly_msg = "Gemini API quota exceeded or rate-limited. Please wait a moment."
            elif code == 404:
                friendly_msg = f"Model not found ({settings.LLM_MODEL}). Will auto-select an available model."
            else:
                friendly_msg = f"Gemini API error ({code}): {getattr(api_err, 'message', str(api_err))}"

            status_obj = {
                "status": "error",
                "model": settings.RESOLVED_LLM_MODEL or settings.LLM_MODEL or "gemini-3.5-flash-lite",
                "message": friendly_msg,
            }
        except Exception as ex:
            err_str = str(ex)
            if "API_KEY" in err_str:
                friendly_msg = "Gemini API key is invalid."
            elif "timed out" in err_str.lower():
                friendly_msg = "Gemini connection timed out. Check network connection."
            else:
                friendly_msg = f"Unable to reach Gemini API: {err_str}"

            status_obj = {
                "status": "error",
                "model": settings.RESOLVED_LLM_MODEL or settings.LLM_MODEL or "gemini-3.5-flash-lite",
                "message": friendly_msg,
            }

        self._cached_status = status_obj
        self._status_timestamp = now
        return status_obj

    def generate(self, prompt: str, retry_count: int = 3) -> Dict[str, Any]:
        """
        Calls Gemini with structured JSON output enforced by LLMOutputModel schema.
        Handles 503 high demand / 429 rate limits with exponential backoff.
        On 404 (model gone), automatically switches to next available candidate.
        """
        if not settings.GEMINI_API_KEY:
            raise ValueError(
                "Gemini API key is missing. Add GEMINI_API_KEY to your .env file to generate queries."
            )

        client = self.get_client()
        active_model = self.resolve_model(client)

        config = types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=LLMOutputModel,
        )

        attempts = 0
        last_error = None

        while attempts < retry_count:
            attempts += 1
            try:
                response = client.models.generate_content(
                    model=active_model,
                    contents=prompt,
                    config=config,
                )

                if not response.text:
                    raise ValueError("Gemini returned an empty response.")

                cleaned_json = clean_json_text(response.text)
                parsed_data = json.loads(cleaned_json)

                # Validate with Pydantic
                validated = LLMOutputModel.model_validate(parsed_data)
                return validated.model_dump()

            except APIError as api_err:
                last_error = api_err
                err_code = getattr(api_err, "code", 0)
                err_msg = str(api_err)

                # Handle 503 high demand or 429 rate limits with backoff
                if err_code in (503, 429) or "UNAVAILABLE" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    wait = attempts * 2.0
                    logger.warning(
                        f"Gemini {err_code} on {active_model}. Backing off {wait}s (attempt {attempts}/{retry_count})..."
                    )
                    time.sleep(wait)
                    continue

                if err_code == 404:
                    # This model is gone — find the next candidate
                    tried = active_model
                    for candidate in FLASH_MODEL_CANDIDATES:
                        if candidate != tried:
                            logger.warning(f"Model {tried} returned 404. Switching to {candidate}...")
                            active_model = candidate
                            settings.RESOLVED_LLM_MODEL = candidate
                            time.sleep(0.5)
                            break
                    else:
                        raise ValueError("No available Gemini model found. Please verify LLM_MODEL in .env.")
                    continue

                if err_code in (401, 403):
                    raise ValueError("Gemini API key is invalid or unauthorized. Please verify GEMINI_API_KEY in .env.")

                raise ValueError(f"Gemini API error ({err_code}): {getattr(api_err, 'message', str(api_err))}")

            except (json.JSONDecodeError, ValueError) as parse_err:
                last_error = parse_err
                if attempts < retry_count:
                    logger.warning(f"Failed parsing Gemini JSON ({parse_err}). Retrying...")
                    prompt = prompt + "\n\nCRITICAL: Respond ONLY with valid, unescaped JSON matching the schema."
                    time.sleep(1.0)
                    continue
                raise ValueError(f"Failed to parse structured response from Gemini: {str(parse_err)}")

            except Exception as ex:
                last_error = ex
                if attempts < retry_count:
                    time.sleep(attempts * 1.5)
                    continue
                raise ValueError(f"Gemini service error: {str(ex)}")

        raise ValueError(
            f"Gemini request could not be completed after {retry_count} attempts: {str(last_error)}"
        )

    def suggest_questions(self, schema_text: str) -> List[str]:
        """
        Suggests 6 relevant, analytical business questions answerable by the user's data schema.
        Cached per schema hash. Returns empty list if Gemini is unavailable.
        """
        if not settings.GEMINI_API_KEY:
            return []

        schema_hash = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
        if schema_hash in self._suggestions_cache:
            return self._suggestions_cache[schema_hash]

        prompt = f"""You are an expert data analyst. Given the following database schema and profile:

{schema_text}

Suggest exactly 6 distinct, useful, and realistic analytical business questions that can be answered from this data.
Questions should cover:
1. Top-N or ranking question
2. Aggregation / summary metric
3. Grouping by a category, city, or status
4. Time-based or recent activity question (if date columns exist)
5. Comparison between two groups or statuses
6. Filter or identification of outliers or inactive entities

OUTPUT CONTRACT:
Respond strictly with valid JSON with this format:
{{
  "questions": [
    "Question 1?",
    "Question 2?",
    "Question 3?",
    "Question 4?",
    "Question 5?",
    "Question 6?"
  ]
}}
"""
        try:
            client = self.get_client()
            active_model = self.resolve_model(client)
            config = types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=active_model,
                contents=prompt,
                config=config,
            )
            cleaned = clean_json_text(response.text)
            data = json.loads(cleaned)
            questions = data.get("questions", [])
            if isinstance(questions, list) and questions:
                clean_qs = [str(q).strip() for q in questions[:6] if str(q).strip()]
                self._suggestions_cache[schema_hash] = clean_qs
                return clean_qs
        except Exception as e:
            logger.warning(f"Could not generate dynamic suggestions from Gemini: {e}")

        return []


gemini_service = GeminiService()
