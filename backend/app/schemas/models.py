"""
Pydantic v2 schemas and models for No2SQL.
"""

from typing import List, Optional, Any, Dict, Literal
from pydantic import BaseModel, Field


class LLMOutputModel(BaseModel):
    """Output contract returned by Google Gemini."""
    status: Literal["ok", "clarification_needed", "unsupported"] = Field(
        description="Outcome of processing: ok (valid query generated), clarification_needed, or unsupported"
    )
    sql: Optional[str] = Field(default=None, description="Generated SELECT SQL query")
    explanation: str = Field(description="Plain-English explanation of what the query accomplishes")
    tables_used: List[str] = Field(default_factory=list, description="Referenced database tables")
    columns_used: List[str] = Field(default_factory=list, description="Referenced database columns")
    assumptions: List[str] = Field(default_factory=list, description="List of assumptions made regarding metrics or dates")
    clarification_question: Optional[str] = Field(default=None, description="Question asked if request was ambiguous")


class QueryGenerateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="User's natural language question")
    share_sample_values: Optional[bool] = Field(default=None, description="Override for sharing sample values with Gemini")


class QueryGenerateResponse(BaseModel):
    request_id: str
    status: Literal["ok", "clarification_needed", "unsupported", "error"]
    sql: Optional[str] = None
    explanation: str
    tables_used: List[str] = Field(default_factory=list)
    columns_used: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None
    query_token: Optional[str] = None


class QueryValidateRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=3000, description="SQL query to validate")


class QueryValidateResponse(BaseModel):
    request_id: str
    allowed: bool
    reason: str
    tables: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)


class QueryExecuteRequest(BaseModel):
    query_token: str = Field(..., min_length=1, description="Opaque token representing a validated query")


class QueryExecuteResponse(BaseModel):
    request_id: str
    success: bool
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: float = 0.0
    error: Optional[str] = None


class LLMStatusResponse(BaseModel):
    status: Literal["connected", "missing_key", "error"]
    model: str
    message: str


class UpdateKeyRequest(BaseModel):
    gemini_api_key: str = Field(..., min_length=1, description="New Gemini API Key")


class UpdateSettingsRequest(BaseModel):
    share_sample_values: Optional[bool] = None


class DataStatusResponse(BaseModel):
    is_loaded: bool
    table_count: int
    total_rows: int
    tables: List[Dict[str, Any]] = Field(default_factory=list)


class DataUploadResponse(BaseModel):
    success: bool
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class DataPreviewResponse(BaseModel):
    table_name: str
    columns: List[str] = Field(default_factory=list)
    original_columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0


class SuggestionsResponse(BaseModel):
    questions: List[str] = Field(default_factory=list)
