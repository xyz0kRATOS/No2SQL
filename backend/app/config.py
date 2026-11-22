"""
Application configuration for No2SQL.
Supports environment variables and .env file loading.
Automatically reads GEMINI_API_KEY from .env (or .env.example fallback).
Stores user workspace database in data/workspace.db.
"""

import os
import shutil
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Root of the no2sql repository (3 levels up from this file)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

env_path = REPO_ROOT / ".env"
env_example_path = REPO_ROOT / ".env.example"

# If .env does not exist, copy from .env.example
if not env_path.exists() and env_example_path.exists():
    shutil.copy(env_example_path, env_path)

# Load .env first
load_dotenv(env_path)
load_dotenv()


def resolve_gemini_api_key() -> str:
    """Reads GEMINI_API_KEY from environment or .env, falling back to .env.example."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        return key

    if env_path.exists():
        vals = dotenv_values(env_path)
        if vals.get("GEMINI_API_KEY"):
            return vals["GEMINI_API_KEY"].strip()

    if env_example_path.exists():
        vals = dotenv_values(env_example_path)
        if vals.get("GEMINI_API_KEY"):
            return vals["GEMINI_API_KEY"].strip()

    return ""


class Settings:
    PROJECT_NAME: str = "No2SQL"
    VERSION: str = "2.1.0"
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # LLM Configuration
    GEMINI_API_KEY: str = resolve_gemini_api_key()
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"

    # Active resolved model name
    RESOLVED_LLM_MODEL: str = ""

    # SQL & Database configuration
    SQL_DIALECT: str = os.getenv("SQL_DIALECT", "sqlite").lower()

    # Workspace directory & database path
    DATA_DIR: Path = REPO_ROOT / "data"
    DB_PATH: Path = REPO_ROOT / "data" / "workspace.db"

    # Upload & safety caps
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    MAX_RESULT_ROWS: int = int(os.getenv("MAX_RESULT_ROWS", "200"))
    QUERY_TIMEOUT_SECONDS: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "8"))

    # Privacy configuration: whether to share sample low-cardinality values with Gemini
    SHARE_SAMPLE_VALUES: bool = os.getenv("SHARE_SAMPLE_VALUES", "true").lower() in ("true", "1", "yes")

    def ensure_data_dir(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def is_database_present(self) -> bool:
        return self.DB_PATH.exists() and self.DB_PATH.stat().st_size > 0


settings = Settings()
settings.ensure_data_dir()
