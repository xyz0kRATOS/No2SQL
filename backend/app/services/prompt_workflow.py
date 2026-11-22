"""
Prompt Workflow for No2SQL.
Assembles dynamic schema and profile context, relative date semantics, and schema-agnostic
few-shot patterns into a structured prompt, calls Gemini with Pydantic JSON enforcement,
validates generated SQL, retries with query repair if needed, and registers execution tokens.
"""

import datetime
import json
import logging
import uuid
from typing import Dict, Any, Optional

from ..config import settings
from .schema_service import schema_service
from .examples import SCHEMA_AGNOSTIC_EXAMPLES
from .llm_provider import gemini_service
from .sql_validator import sql_validator
from .query_executor import query_executor
from ..schemas.models import LLMOutputModel

logger = logging.getLogger("no2sql.workflow")


class PromptWorkflow:
    def __init__(self):
        pass

    def build_system_prompt(self, share_sample_values: Optional[bool] = None) -> str:
        dialect = settings.SQL_DIALECT
        today_str = datetime.date.today().isoformat()
        schema_text = schema_service.format_schema_for_prompt(share_sample_values=share_sample_values)

        date_guidance = f"""
SQLITE DATE COMPUTATION RULES:
- Today's Reference Date: {today_str}
- "This month" (current calendar month):
    date_col >= date('now', 'start of month') AND date_col < date('now', 'start of month', '+1 month')
- "Last month" (previous calendar month):
    date_col >= date('now', 'start of month', '-1 month') AND date_col < date('now', 'start of month')
- "Past 30 days":
    date_col >= date('now', '-30 days')
- "This year":
    date_col >= date('now', 'start of year') AND date_col < date('now', 'start of year', '+1 year')
- Monthly formatting:
    strftime('%Y-%m', date_col)
- Year formatting:
    strftime('%Y', date_col)
NOTE ON DATE RANGES: If the user asks for a time period (e.g. "last month", "this year") and the column's date range in the schema profile shows the uploaded data does not cover that period, state this clearly in "assumptions" and suggest the actual date range covered by the dataset.
"""

        # Format schema-agnostic few-shot examples
        examples_str_list = []
        for idx, ex in enumerate(SCHEMA_AGNOSTIC_EXAMPLES, 1):
            ex_json = json.dumps(
                {
                    "status": ex["status"],
                    "sql": ex.get("sql"),
                    "explanation": ex["explanation"],
                    "tables_used": ex.get("tables_used", []),
                    "columns_used": ex.get("columns_used", []),
                    "assumptions": ex.get("assumptions", []),
                    "clarification_question": ex.get("clarification_question"),
                },
                indent=2,
            )
            examples_str_list.append(f"Pattern Example {idx} (ILLUSTRATIVE ONLY - DO NOT USE THESE TABLE NAMES):\nUser: {ex['question']}\nAssistant JSON:\n{ex_json}\n")

        examples_section = "\n".join(examples_str_list)

        prompt = f"""You are an expert SQL engineer. You translate business questions into a single read-only {dialect.upper()} SELECT query.

{schema_text}

{date_guidance}

STRICT SAFETY AND BUSINESS RULES:
1. ONLY read-only queries are permitted. Single SELECT or WITH ... SELECT statement only.
2. If the user asks to modify, delete, insert, drop, truncate, or alter anything (e.g. "delete rows"), return status="unsupported" with a friendly explanation that the tool is strictly read-only.
3. If the user requests data that does not exist in the uploaded database schema, return status="unsupported" explaining which specific data or entity is missing.
4. If a request is ambiguous (e.g., asking for "sales" or "revenue" when multiple numeric columns or amounts exist, or missing a grouping dimension), return status="clarification_needed" and provide a helpful clarification_question that specifically names the candidate columns.
5. Use ONLY the tables and columns explicitly listed in the active database schema above. Never hallucinate or invent tables, columns, or joins.
6. When filtering on categorical text columns (e.g. status, city, category), check the provided sample values in the schema profile and use the exact string values seen (use case-insensitive comparison LIKE or COLLATE NOCASE if uncertain).
7. Inferred relationships: Join tables on the inferred relationships or common keys identified in the schema.
8. Always alias computed or aggregated columns clearly (e.g. AS total_amount, AS order_count).

OUTPUT CONTRACT:
You MUST respond strictly with valid JSON. Do not wrap in markdown or backticks.
Schema:
{{
  "status": "ok | clarification_needed | unsupported",
  "sql": "SELECT ... or null",
  "explanation": "Clear, non-technical plain-English explanation",
  "tables_used": ["table1", "table2"],
  "columns_used": ["table1.col1", "table2.col2"],
  "assumptions": ["List of assumptions"],
  "clarification_question": "Question string if clarification_needed, else null"
}}

ILLUSTRATIVE PATTERNS (DO NOT COPY TABLE NAMES FROM THESE EXAMPLES):
{examples_section}
"""
        return prompt

    def process_question(
        self,
        question: str,
        request_id: Optional[str] = None,
        share_sample_values: Optional[bool] = None,
    ) -> Dict[str, Any]:
        req_id = request_id or str(uuid.uuid4())

        # Check if database is loaded
        allowed_tables = schema_service.get_allowed_tables()
        if not allowed_tables:
            return {
                "request_id": req_id,
                "status": "unsupported",
                "sql": None,
                "explanation": "No data has been uploaded to the workspace yet. Please upload your files (CSV, Excel, JSON, SQLite) to get started.",
                "tables_used": [],
                "columns_used": [],
                "assumptions": ["Workspace database is empty."],
                "clarification_question": None,
                "validation": None,
                "query_token": None,
            }

        # Check if Gemini key is configured
        if not settings.GEMINI_API_KEY:
            raise ValueError(
                "Gemini API key is missing. Add GEMINI_API_KEY to your .env file or Settings to generate queries."
            )

        base_system_prompt = self.build_system_prompt(share_sample_values=share_sample_values)
        full_prompt = f"{base_system_prompt}\n\nUser Question: {question}\nAssistant JSON:"

        # Generate response using real Gemini SDK
        parsed = gemini_service.generate(full_prompt)

        # Self-repair loop: if SQL was generated, validate it
        if parsed.get("status") == "ok" and parsed.get("sql"):
            sql = parsed["sql"]
            val_result = sql_validator.validate(sql, allowed_tables=allowed_tables)

            # If validation failed, attempt one repair turn with Gemini
            if not val_result["allowed"]:
                logger.warning(f"Initial SQL failed validation ({val_result['reason']}). Requesting Gemini repair...")
                repair_prompt = f"""{base_system_prompt}

User Question: {question}

Your previous SQL query:
{sql}

Failed security or schema validation with this reason:
{val_result['reason']}

Please repair the SQL query so that it uses ONLY the allowed tables ({', '.join(allowed_tables)}) and valid columns.
Respond with the same JSON schema."""
                try:
                    repaired = gemini_service.generate(repair_prompt)
                    if repaired.get("status") == "ok" and repaired.get("sql"):
                        repaired_val = sql_validator.validate(repaired["sql"], allowed_tables=allowed_tables)
                        if repaired_val["allowed"]:
                            parsed = repaired
                            val_result = repaired_val
                except Exception as ex:
                    logger.warning(f"Query repair attempt failed: {ex}")

            # Final validation check
            if val_result["allowed"]:
                # Cross-check and synchronize tables/columns from validator AST
                if val_result.get("tables"):
                    parsed["tables_used"] = val_result["tables"]
                if val_result.get("columns"):
                    parsed["columns_used"] = val_result["columns"]

                token = query_executor.register_query_token(parsed["sql"], question)
                return {
                    "request_id": req_id,
                    "status": "ok",
                    "sql": parsed["sql"],
                    "explanation": parsed["explanation"],
                    "tables_used": parsed["tables_used"],
                    "columns_used": parsed["columns_used"],
                    "assumptions": parsed.get("assumptions", []),
                    "clarification_question": None,
                    "validation": val_result,
                    "query_token": token,
                }
            else:
                return {
                    "request_id": req_id,
                    "status": "unsupported",
                    "sql": parsed.get("sql"),
                    "explanation": f"Generated query did not pass safety/schema rules: {val_result['reason']}",
                    "tables_used": [],
                    "columns_used": [],
                    "assumptions": parsed.get("assumptions", []),
                    "clarification_question": None,
                    "validation": val_result,
                    "query_token": None,
                }

        return {
            "request_id": req_id,
            "status": parsed.get("status", "unsupported"),
            "sql": None,
            "explanation": parsed.get("explanation", ""),
            "tables_used": parsed.get("tables_used", []),
            "columns_used": parsed.get("columns_used", []),
            "assumptions": parsed.get("assumptions", []),
            "clarification_question": parsed.get("clarification_question"),
            "validation": None,
            "query_token": None,
        }


prompt_workflow = PromptWorkflow()
