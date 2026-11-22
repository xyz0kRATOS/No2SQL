"""
API Routes for No2SQL.
Provides:
- /api/llm/status, /api/llm/key, /api/settings
- /api/data/upload, /api/data/status, /api/data/preview, /api/data, /api/data/suggestions
- /api/schema
- /api/query/generate, /api/query/validate, /api/query/execute
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, status

from ..config import settings
from ..schemas.models import (
    LLMStatusResponse,
    UpdateKeyRequest,
    UpdateSettingsRequest,
    DataStatusResponse,
    DataUploadResponse,
    DataPreviewResponse,
    SuggestionsResponse,
    QueryGenerateRequest,
    QueryGenerateResponse,
    QueryValidateRequest,
    QueryValidateResponse,
    QueryExecuteRequest,
    QueryExecuteResponse,
)
from ..services.data_service import data_service
from ..services.schema_service import schema_service
from ..services.llm_provider import gemini_service
from ..services.prompt_workflow import prompt_workflow
from ..services.sql_validator import sql_validator
from ..services.query_executor import query_executor

router = APIRouter(prefix="/api", tags=["No2SQL API"])


# -------------------------------------------------------------
# LLM & Settings Endpoints
# -------------------------------------------------------------

@router.get("/llm/status", response_model=LLMStatusResponse)
def get_llm_status(refresh: bool = False):
    """
    Checks Gemini API readiness via a real lightweight call (cached for 60s).
    Returns connected, missing_key, or error. Never reveals the API key.
    """
    res = gemini_service.check_connection_status(force_refresh=refresh)
    return LLMStatusResponse(**res)


@router.post("/llm/key", response_model=LLMStatusResponse)
def update_llm_key(req: UpdateKeyRequest):
    """
    Updates the Gemini API key in memory and in the local .env file,
    then tests the connection immediately.
    """
    new_key = req.gemini_api_key.strip()
    if not new_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key cannot be empty.",
        )
    settings.update_gemini_api_key(new_key)
    # Clear model cache to trigger re-check
    settings.RESOLVED_LLM_MODEL = ""
    res = gemini_service.check_connection_status(force_refresh=True)
    return LLMStatusResponse(**res)


@router.post("/settings")
def update_settings(req: UpdateSettingsRequest):
    """Updates runtime privacy and generation settings."""
    if req.share_sample_values is not None:
        settings.SHARE_SAMPLE_VALUES = req.share_sample_values
    return {
        "success": True,
        "share_sample_values": settings.SHARE_SAMPLE_VALUES,
        "sql_dialect": settings.SQL_DIALECT,
        "max_result_rows": settings.MAX_RESULT_ROWS,
    }


@router.get("/settings")
def get_settings():
    """Returns current active settings (excluding secrets)."""
    return {
        "share_sample_values": settings.SHARE_SAMPLE_VALUES,
        "sql_dialect": settings.SQL_DIALECT,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "max_result_rows": settings.MAX_RESULT_ROWS,
        "query_timeout_seconds": settings.QUERY_TIMEOUT_SECONDS,
        "model": settings.RESOLVED_LLM_MODEL or settings.LLM_MODEL,
    }


# -------------------------------------------------------------
# Data Ingestion & Workspace Endpoints
# -------------------------------------------------------------

@router.get("/data/status", response_model=DataStatusResponse)
def get_data_status():
    """Returns workspace loaded state, table count, and table row counts."""
    return DataStatusResponse(**data_service.get_workspace_status())


@router.post("/data/upload", response_model=DataUploadResponse)
async def upload_data_files(
    files: List[UploadFile] = File(...),
    mode: str = Form("replace"),
):
    """
    Uploads one or more files (.csv, .tsv, .xlsx, .xls, .json, .jsonl, .parquet, .db),
    sanitizes names, infers types, and loads into workspace.db.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files were provided for upload.",
        )

    clean_mode = mode.lower()
    if clean_mode not in ("replace", "append"):
        clean_mode = "replace"

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    total_bytes = 0
    file_payloads = []

    for f in files:
        content = await f.read()
        total_bytes += len(content)
        if total_bytes > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Total upload size exceeds the maximum limit of {settings.MAX_UPLOAD_MB} MB.",
            )
        file_payloads.append((f.filename or "uploaded_data.csv", content))

    try:
        result = data_service.ingest_files(file_payloads, mode=clean_mode)
        return DataUploadResponse(
            success=True,
            tables=result["tables"],
            warnings=result["warnings"],
        )
    except Exception as e:
        req_id = str(uuid.uuid4())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest uploaded data: {str(e)} (Request ID: {req_id})",
        )


@router.get("/data/preview", response_model=DataPreviewResponse)
def preview_table(table: str = Query(..., description="Table name to preview"), limit: int = 10):
    """Returns safe preview rows for the specified table."""
    try:
        preview_data = data_service.preview_table(table_name=table, limit=min(limit, 50))
        return DataPreviewResponse(**preview_data)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as ex:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Preview error: {str(ex)}")


@router.delete("/data")
def clear_workspace_data():
    """Clears all tables from the workspace database."""
    success = data_service.clear_workspace()
    return {"success": success, "message": "All workspace data cleared successfully."}


@router.get("/data/suggestions", response_model=SuggestionsResponse)
def get_question_suggestions():
    """Generates 6 contextual business questions based on the active dataset schema."""
    schema_text = schema_service.format_schema_for_prompt()
    if "No tables or data have been loaded" in schema_text:
        return SuggestionsResponse(questions=[])

    questions = gemini_service.suggest_questions(schema_text)
    return SuggestionsResponse(questions=questions)


# -------------------------------------------------------------
# Schema & Query Endpoints
# -------------------------------------------------------------

@router.get("/schema")
def get_schema():
    """Returns dynamic database schema metadata, column profiles, and inferred relationships."""
    try:
        return schema_service.inspect_schema()
    except Exception as e:
        req_id = str(uuid.uuid4())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to read schema: {str(e)} (Request ID: {req_id})",
        )


@router.post("/query/generate", response_model=QueryGenerateResponse)
def generate_query(req: QueryGenerateRequest):
    """
    Translates a natural language question into a safe, validated read-only SQL query using Gemini.
    Generating SQL NEVER automatically executes it.
    """
    req_id = str(uuid.uuid4())
    cleaned_question = req.question.strip()
    if not cleaned_question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Question cannot be empty. Request ID: {req_id}",
        )

    try:
        result = prompt_workflow.process_question(
            cleaned_question,
            request_id=req_id,
            share_sample_values=req.share_sample_values,
        )
        return QueryGenerateResponse(**result)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{str(ve)} (Request ID: {req_id})",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate query: {str(e)} (Request ID: {req_id})",
        )


@router.post("/query/validate", response_model=QueryValidateResponse)
def validate_query(req: QueryValidateRequest):
    """Validates arbitrary SQL against AST safety rules and allowed tables."""
    req_id = str(uuid.uuid4())
    cleaned_sql = req.sql.strip()
    if not cleaned_sql:
        return QueryValidateResponse(
            request_id=req_id,
            allowed=False,
            reason="SQL query cannot be empty.",
            tables=[],
            columns=[],
        )

    val = sql_validator.validate(cleaned_sql)
    return QueryValidateResponse(
        request_id=req_id,
        allowed=val["allowed"],
        reason=val["reason"],
        tables=val.get("tables", []),
        columns=val.get("columns", []),
    )


@router.post("/query/execute", response_model=QueryExecuteResponse)
def execute_query(req: QueryExecuteRequest):
    """
    Executes a previously validated query using an opaque query_token.
    Raw SQL is NEVER accepted directly at this endpoint.
    """
    req_id = str(uuid.uuid4())
    token = req.query_token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing query token. Request ID: {req_id}",
        )

    result = query_executor.execute_token(token)

    if not result.get("success", False):
        status_code = result.get("status_code", status.HTTP_400_BAD_REQUEST)
        error_msg = result.get("error", "Execution failed")
        raise HTTPException(
            status_code=status_code,
            detail=f"{error_msg} (Request ID: {req_id})",
        )

    return QueryExecuteResponse(
        request_id=req_id,
        success=True,
        columns=result.get("columns", []),
        rows=result.get("rows", []),
        row_count=result.get("row_count", 0),
        truncated=result.get("truncated", False),
        duration_ms=result.get("duration_ms", 0.0),
        error=None,
    )
