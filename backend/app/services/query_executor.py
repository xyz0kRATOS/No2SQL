"""
Query Executor for No2SQL.
Executes read-only SQL queries against SQLite with:
- Defense-in-depth: SQLite read-only URI + PRAGMA query_only = ON
- Hardware timeout handler via connection.set_progress_handler
- Row capping at MAX_RESULT_ROWS and truncation detection
- Secure token-based execution (raw SQL is never accepted at the execute endpoint)
- Clean, user-friendly error messages with no exposed stack traces
"""

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..config import settings
from .sql_validator import sql_validator


class QueryExecutor:
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or settings.DB_PATH
        # In-memory token store: token -> {"sql": str, "question": str, "created_at": float}
        self._token_store: Dict[str, Dict[str, Any]] = {}

    def register_query_token(self, sql: str, question: str) -> str:
        token = str(uuid.uuid4())
        self._token_store[token] = {
            "sql": sql,
            "question": question,
            "created_at": time.time(),
        }
        return token

    def get_query_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        return self._token_store.get(token)

    def execute_token(self, token: str) -> Dict[str, Any]:
        record = self.get_query_by_token(token)
        if not record:
            return {
                "success": False,
                "error": "Invalid or expired query token. Please generate a new query.",
                "status_code": 404,
            }

        sql = record["sql"]

        # Re-validate immediately before running as defense-in-depth
        validation = sql_validator.validate(sql)
        if not validation["allowed"]:
            return {
                "success": False,
                "error": f"Security validation failed prior to execution: {validation['reason']}",
                "status_code": 422,
            }

        return self.execute_sql(sql)

    def execute_sql(self, sql: str) -> Dict[str, Any]:
        if not self._db_path.exists():
            return {
                "success": False,
                "error": f"Database file not found at {self._db_path.name}. Please ensure database is seeded.",
                "status_code": 500,
            }

        start_time = time.perf_counter()
        timeout_seconds = settings.QUERY_TIMEOUT_SECONDS
        deadline = time.time() + timeout_seconds

        def timeout_progress_handler():
            if time.time() > deadline:
                return 1  # Abort SQLite query
            return 0

        conn = None
        try:
            # Mode=ro with URI flag ensures SQLite engine itself blocks any write
            db_uri = f"file:{self._db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(db_uri, uri=True, timeout=timeout_seconds)

            # Extra defense in depth
            conn.execute("PRAGMA query_only = ON;")

            # Register interrupt handler: checked every 100 opcodes
            conn.set_progress_handler(timeout_progress_handler, 100)

            cur = conn.cursor()
            cur.execute(sql)

            columns = [desc[0] for desc in cur.description] if cur.description else []

            # Fetch up to MAX_RESULT_ROWS + 1 to detect if truncation occurred
            max_rows = settings.MAX_RESULT_ROWS
            raw_rows = cur.fetchmany(max_rows + 1)

            truncated = False
            if len(raw_rows) > max_rows:
                truncated = True
                rows = [list(r) for r in raw_rows[:max_rows]]
            else:
                rows = [list(r) for r in raw_rows]

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
                "duration_ms": duration_ms,
            }

        except sqlite3.OperationalError as oe:
            err_msg = str(oe)
            if "interrupted" in err_msg.lower():
                return {
                    "success": False,
                    "error": f"Query execution timed out after exceeding {timeout_seconds} seconds limit.",
                    "status_code": 408,
                }
            return {
                "success": False,
                "error": f"Database query error: {err_msg}",
                "status_code": 400,
            }
        except sqlite3.DatabaseError as de:
            return {
                "success": False,
                "error": f"Database error encountered: {str(de)}",
                "status_code": 400,
            }
        except Exception as ex:
            return {
                "success": False,
                "error": "An unexpected error occurred while executing the query.",
                "status_code": 500,
            }
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


# Singleton executor
query_executor = QueryExecutor()
