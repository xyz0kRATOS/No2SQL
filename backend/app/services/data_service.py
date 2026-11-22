"""
Data Service for No2SQL.
Handles multi-format file ingestion (CSV, TSV, XLSX, XLS, JSON, JSONL, Parquet, SQLite .db),
intelligent name sanitization, type inference, messy data resilience,
and persistence in data/workspace.db.
"""

import csv
import io
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import pandas as pd

from ..config import settings

logger = logging.getLogger("no2sql.data")

SQL_RESERVED_WORDS = {
    "add", "all", "alter", "and", "as", "asc", "autoincrement", "between", "by", "case",
    "check", "collate", "column", "commit", "constraint", "create", "cross", "current_date",
    "current_time", "current_timestamp", "database", "default", "deferrable", "deferred",
    "delete", "desc", "distinct", "drop", "each", "else", "end", "escape", "except", "exclusive",
    "exists", "explain", "fail", "for", "foreign", "from", "full", "glob", "group", "having",
    "if", "ignore", "immediate", "in", "index", "indexed", "initially", "inner", "insert",
    "instead", "intersect", "into", "is", "isnull", "join", "key", "left", "like", "limit",
    "match", "natural", "no", "not", "notnull", "null", "of", "offset", "on", "or", "order",
    "outer", "plan", "pragma", "primary", "query", "raise", "recursive", "references", "regexp",
    "reindex", "release", "rename", "replace", "restrict", "right", "rollback", "row", "savepoint",
    "select", "set", "table", "temp", "temporary", "then", "to", "transaction", "trigger",
    "union", "unique", "update", "using", "vacuum", "values", "view", "virtual", "when", "where",
    "user", "order"
}

CURRENCY_REGEX = re.compile(r"^[₹$€£¥]?\s*-?\d{1,3}(,\d{3})*(\.\d+)?\s*[₹$€£¥]?$")


def sanitize_identifier(raw: str, prefix_default: str = "col") -> str:
    """
    Converts any raw string into a clean SQL identifier:
    - lower_snake_case
    - only a-z, 0-9, and _
    - does not start with a digit
    - appends _ if SQL reserved word
    """
    s = str(raw).strip().lower()
    # Replace whitespace and separators with underscore
    s = re.sub(r"[\s\-\.\/\\]+", "_", s)
    # Strip any characters that aren't alphanumeric or underscore
    s = re.sub(r"[^a-z0-9_]", "", s)
    # Clean multiple underscores
    s = re.sub(r"_+", "_", s).strip("_")

    if not s:
        s = prefix_default
    elif s[0].isdigit():
        s = f"{prefix_default}_{s}"

    if s in SQL_RESERVED_WORDS:
        s = f"{s}_"

    return s


def sanitize_column_names(columns: List[Any]) -> Tuple[List[str], Dict[str, str]]:
    """
    Sanitizes header columns, handles empty headers, and deduplicates column names.
    Returns: (list_of_clean_names, mapping_clean_to_original)
    """
    clean_cols = []
    clean_to_orig = {}
    seen = {}

    for idx, col in enumerate(columns):
        orig_str = str(col) if col is not None else f"Column_{idx + 1}"
        base_clean = sanitize_identifier(orig_str, prefix_default=f"col_{idx + 1}")

        if base_clean in seen:
            seen[base_clean] += 1
            final_clean = f"{base_clean}_{seen[base_clean]}"
        else:
            seen[base_clean] = 1
            final_clean = base_clean

        clean_cols.append(final_clean)
        clean_to_orig[final_clean] = orig_str

    return clean_cols, clean_to_orig


def try_parse_numeric_series(series: pd.Series) -> Optional[pd.Series]:
    """Attempts to strip currency/commas and convert to numeric if safe."""
    non_null = series.dropna().astype(str).str.strip()
    if non_null.empty:
        return None

    # Check if a high proportion matches numeric pattern with optional currency/commas
    matches = non_null.apply(lambda x: bool(CURRENCY_REGEX.match(x)))
    if matches.mean() >= 0.80:
        cleaned = series.astype(str).str.replace(r"[₹$€£¥,\s]", "", regex=True)
        try:
            return pd.to_numeric(cleaned, errors="coerce")
        except Exception:
            return None
    return None


def try_parse_date_series(series: pd.Series) -> Optional[pd.Series]:
    """Attempts to parse series as datetime and format to YYYY-MM-DD text."""
    non_null = series.dropna().astype(str).str.strip()
    if non_null.empty:
        return None

    # Sample non-empty to avoid scanning huge series if definitely not dates
    sample = non_null.head(100)
    has_date_chars = sample.str.contains(r"[\-\/\:]", regex=True).mean()
    if has_date_chars < 0.6:
        return None

    try:
        parsed = pd.to_datetime(series, errors="coerce")
        # Check if enough non-nulls were successfully parsed
        valid_ratio = parsed.notna().sum() / max(1, len(non_null))
        if valid_ratio >= 0.80:
            # Check if times are all zero (pure date)
            has_time = (parsed.dt.hour != 0) | (parsed.dt.minute != 0) | (parsed.dt.second != 0)
            if has_time.any():
                return parsed.dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                return parsed.dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def clean_and_infer_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str], List[str]]:
    """
    Cleans DataFrame, infers types (int, float, date, boolean, text),
    strips whitespace, replaces empty strings with NULL.
    Returns: (cleaned_df, clean_to_original_col_map, warnings)
    """
    warnings = []

    if df.empty and len(df.columns) == 0:
        return df, {}, ["Table contains no data or columns."]

    # If first row looks like headers because of messy Excel/CSV read
    if len(df) > 0 and all(isinstance(c, int) for c in df.columns):
        # Header was integers 0, 1, 2... check if row 0 has strings
        first_row = df.iloc[0]
        if first_row.notna().mean() >= 0.5:
            df.columns = [str(x) for x in first_row.values]
            df = df.iloc[1:].reset_index(drop=True)

    if len(df.columns) > 200:
        warnings.append(f"Table has {len(df.columns)} columns (exceeds recommended 200).")

    # Sanitize column names
    clean_cols, clean_to_orig = sanitize_column_names(df.columns)
    df.columns = clean_cols

    # Process each column
    for col in clean_cols:
        series = df[col]

        # Convert empty strings and whitespace strings to None
        if series.dtype == object:
            series = series.apply(lambda x: None if (isinstance(x, str) and not x.strip()) else x)

        # Check for currency / formatted numeric
        if series.dtype == object:
            num_series = try_parse_numeric_series(series)
            if num_series is not None:
                series = num_series

        # Check for dates
        if series.dtype == object:
            date_series = try_parse_date_series(series)
            if date_series is not None:
                series = date_series

        # Check booleans (true/false, yes/no)
        if series.dtype == object:
            non_null_str = series.dropna().astype(str).str.lower().str.strip()
            bool_map = {"true": 1, "false": 0, "yes": 1, "no": 0, "y": 1, "n": 0}
            if not non_null_str.empty and non_null_str.isin(bool_map.keys()).mean() >= 0.90:
                series = series.astype(str).str.lower().str.strip().map(bool_map)

        # Clean string whitespace
        if series.dtype == object:
            series = series.apply(lambda x: x.strip() if isinstance(x, str) else x)

        df[col] = series

    return df, clean_to_orig, warnings


class DataService:
    def __init__(self):
        self.db_path = settings.DB_PATH

    def get_connection(self, read_only: bool = False) -> sqlite3.Connection:
        settings.ensure_data_dir()
        if read_only:
            if not settings.is_database_present():
                raise FileNotFoundError("Workspace database is not loaded. Please upload data first.")
            conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_metadata_table(self, conn: sqlite3.Connection):
        """Ensures the internal metadata table exists."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _no2sql_metadata (
                table_name TEXT NOT NULL,
                clean_column TEXT NOT NULL,
                original_column TEXT NOT NULL,
                inferred_type TEXT NOT NULL,
                PRIMARY KEY (table_name, clean_column)
            );
        """)
        conn.commit()

    def get_column_mapping(self, table_name: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        """Returns {table_name: {clean_col: original_col}}."""
        if not settings.is_database_present():
            return {}
        try:
            conn = self.get_connection(read_only=True)
            cur = conn.cursor()
            if table_name:
                cur.execute(
                    "SELECT table_name, clean_column, original_column FROM _no2sql_metadata WHERE table_name = ?",
                    (table_name,),
                )
            else:
                cur.execute("SELECT table_name, clean_column, original_column FROM _no2sql_metadata")
            rows = cur.fetchall()
            conn.close()

            result = {}
            for r in rows:
                t = r["table_name"]
                if t not in result:
                    result[t] = {}
                result[t][r["clean_column"]] = r["original_column"]
            return result
        except Exception:
            return {}

    def get_workspace_status(self) -> Dict[str, Any]:
        """Returns workspace loading status, table count, and table summaries."""
        if not settings.is_database_present():
            return {
                "is_loaded": False,
                "table_count": 0,
                "total_rows": 0,
                "tables": [],
            }

        try:
            conn = self.get_connection(read_only=True)
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_no2sql_%' ORDER BY name"
            )
            table_names = [r["name"] for r in cur.fetchall()]

            tables = []
            total_rows = 0

            for t in table_names:
                cur.execute(f'SELECT COUNT(*) as count FROM "{t}"')
                cnt = cur.fetchone()["count"]
                total_rows += cnt

                cur.execute(f'PRAGMA table_info("{t}")')
                col_count = len(cur.fetchall())

                tables.append({
                    "name": t,
                    "row_count": cnt,
                    "column_count": col_count,
                })

            conn.close()
            return {
                "is_loaded": len(tables) > 0,
                "table_count": len(tables),
                "total_rows": total_rows,
                "tables": tables,
            }
        except Exception as e:
            logger.warning(f"Error checking workspace status: {e}")
            return {
                "is_loaded": False,
                "table_count": 0,
                "total_rows": 0,
                "tables": [],
            }

    def clear_workspace(self) -> bool:
        """Removes the workspace database and clears all user data."""
        if self.db_path.exists():
            try:
                self.db_path.unlink()
                logger.info("Workspace database cleared successfully.")
                return True
            except Exception as e:
                logger.error(f"Failed to delete workspace database: {e}")
                # Fallback: drop all tables
                conn = sqlite3.connect(self.db_path)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                tables = [r[0] for r in cur.fetchall()]
                for t in tables:
                    cur.execute(f'DROP TABLE IF EXISTS "{t}"')
                conn.commit()
                conn.close()
                return True
        return True

    def import_sqlite_database(self, source_db_bytes: bytes, mode: str = "replace") -> Tuple[List[Dict[str, Any]], List[str]]:
        """Imports tables from an uploaded SQLite .db file into workspace.db."""
        warnings = []
        created_tables = []

        # Write temp source DB to read
        temp_src = settings.DATA_DIR / "_temp_upload_source.db"
        temp_src.write_bytes(source_db_bytes)

        try:
            src_conn = sqlite3.connect(temp_src)
            src_cur = src_conn.cursor()
            src_cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_no2sql_%'"
            )
            tables = [r[0] for r in src_cur.fetchall()]

            dest_conn = self.get_connection(read_only=False)
            self.init_metadata_table(dest_conn)

            for t in tables:
                clean_t = sanitize_identifier(t, prefix_default="tbl")
                df = pd.read_sql_query(f'SELECT * FROM "{t}"', src_conn)
                cleaned_df, clean_to_orig, df_warns = clean_and_infer_dataframe(df)
                warnings.extend(df_warns)

                if mode == "replace":
                    dest_conn.execute(f'DROP TABLE IF EXISTS "{clean_t}"')
                    dest_conn.execute(
                        "DELETE FROM _no2sql_metadata WHERE table_name = ?", (clean_t,)
                    )

                cleaned_df.to_sql(clean_t, dest_conn, if_exists=mode, index=False)

                # Update metadata
                for c in cleaned_df.columns:
                    col_type = str(cleaned_df[c].dtype)
                    dest_conn.execute(
                        """
                        INSERT OR REPLACE INTO _no2sql_metadata (table_name, clean_column, original_column, inferred_type)
                        VALUES (?, ?, ?, ?)
                        """,
                        (clean_t, c, clean_to_orig.get(c, c), col_type),
                    )

                created_tables.append({
                    "name": clean_t,
                    "row_count": len(cleaned_df),
                    "columns": [{"name": c, "original_name": clean_to_orig.get(c, c), "type": str(cleaned_df[c].dtype)} for c in cleaned_df.columns],
                    "warnings": df_warns,
                })

            dest_conn.commit()
            dest_conn.close()
            src_conn.close()
        finally:
            if temp_src.exists():
                try:
                    temp_src.unlink()
                except Exception:
                    pass

        return created_tables, warnings

    def ingest_files(self, files: List[Tuple[str, bytes]], mode: str = "replace") -> Dict[str, Any]:
        """
        Ingests a batch of files into workspace.db.
        files: list of (filename, file_bytes)
        mode: 'replace' | 'append'
        """
        all_created_tables = []
        all_warnings = []

        dest_conn = self.get_connection(read_only=False)
        self.init_metadata_table(dest_conn)

        for filename, content_bytes in files:
            ext = Path(filename).suffix.lower()
            base_name = Path(filename).stem
            file_warns = []

            if len(content_bytes) == 0:
                all_warnings.append(f"File '{filename}' is empty; skipped.")
                continue

            try:
                # 1. SQLite database
                if ext in (".db", ".sqlite", ".sqlite3"):
                    tables_res, warns = self.import_sqlite_database(content_bytes, mode=mode)
                    all_created_tables.extend(tables_res)
                    all_warnings.extend(warns)
                    continue

                # 2. Excel spreadsheets (each sheet becomes a table)
                if ext in (".xlsx", ".xls"):
                    excel_file = pd.ExcelFile(io.BytesIO(content_bytes))
                    for sheet_name in excel_file.sheet_names:
                        df_sheet = excel_file.parse(sheet_name)
                        if df_sheet.empty or len(df_sheet.columns) == 0:
                            file_warns.append(f"Sheet '{sheet_name}' in '{filename}' is empty; skipped.")
                            continue

                        # Table name from file and sheet name if multiple sheets, or sheet name
                        if len(excel_file.sheet_names) > 1:
                            t_raw = f"{base_name}_{sheet_name}"
                        else:
                            t_raw = base_name

                        table_name = sanitize_identifier(t_raw, prefix_default="tbl")
                        cleaned_df, clean_to_orig, c_warns = clean_and_infer_dataframe(df_sheet)
                        file_warns.extend(c_warns)

                        if mode == "replace":
                            dest_conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                            dest_conn.execute("DELETE FROM _no2sql_metadata WHERE table_name = ?", (table_name,))

                        cleaned_df.to_sql(table_name, dest_conn, if_exists=mode, index=False)

                        for c in cleaned_df.columns:
                            dest_conn.execute(
                                """
                                INSERT OR REPLACE INTO _no2sql_metadata (table_name, clean_column, original_column, inferred_type)
                                VALUES (?, ?, ?, ?)
                                """,
                                (table_name, c, clean_to_orig.get(c, c), str(cleaned_df[c].dtype)),
                            )

                        all_created_tables.append({
                            "name": table_name,
                            "row_count": len(cleaned_df),
                            "columns": [{"name": c, "original_name": clean_to_orig.get(c, c), "type": str(cleaned_df[c].dtype)} for c in cleaned_df.columns],
                            "warnings": c_warns,
                        })
                    continue

                # 3. CSV / TSV / TXT
                if ext in (".csv", ".tsv", ".txt"):
                    # Auto-detect encoding
                    text_content = None
                    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                        try:
                            text_content = content_bytes.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue

                    if text_content is None:
                        all_warnings.append(f"Could not decode file '{filename}' with utf-8 or latin-1 encodings.")
                        continue

                    # Auto-detect delimiter
                    delimiter = ","
                    if ext == ".tsv":
                        delimiter = "\t"
                    else:
                        sample_chunk = text_content[:4096]
                        try:
                            dialect = csv.Sniffer().sniff(sample_chunk, delimiters=[",", "\t", ";", "|"])
                            delimiter = dialect.delimiter
                        except Exception:
                            # Count occurrences in first line
                            first_line = sample_chunk.split("\n")[0] if "\n" in sample_chunk else sample_chunk
                            counts = {sep: first_line.count(sep) for sep in (",", "\t", ";", "|")}
                            best_sep = max(counts, key=counts.get)
                            if counts[best_sep] > 0:
                                delimiter = best_sep

                    df = pd.read_csv(io.StringIO(text_content), sep=delimiter)
                    table_name = sanitize_identifier(base_name, prefix_default="tbl")
                    cleaned_df, clean_to_orig, c_warns = clean_and_infer_dataframe(df)
                    file_warns.extend(c_warns)

                    if mode == "replace":
                        dest_conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                        dest_conn.execute("DELETE FROM _no2sql_metadata WHERE table_name = ?", (table_name,))

                    cleaned_df.to_sql(table_name, dest_conn, if_exists=mode, index=False)

                    for c in cleaned_df.columns:
                        dest_conn.execute(
                            """
                            INSERT OR REPLACE INTO _no2sql_metadata (table_name, clean_column, original_column, inferred_type)
                            VALUES (?, ?, ?, ?)
                            """,
                            (table_name, c, clean_to_orig.get(c, c), str(cleaned_df[c].dtype)),
                        )

                    all_created_tables.append({
                        "name": table_name,
                        "row_count": len(cleaned_df),
                        "columns": [{"name": c, "original_name": clean_to_orig.get(c, c), "type": str(cleaned_df[c].dtype)} for c in cleaned_df.columns],
                        "warnings": c_warns,
                    })
                    continue

                # 4. JSON / JSONL
                if ext in (".json", ".jsonl"):
                    text_content = content_bytes.decode("utf-8", errors="replace")
                    if ext == ".jsonl":
                        lines = [json.loads(line) for line in text_content.strip().splitlines() if line.strip()]
                        df = pd.DataFrame(lines)
                    else:
                        raw_json = json.loads(text_content)
                        if isinstance(raw_json, list):
                            df = pd.DataFrame(raw_json)
                        elif isinstance(raw_json, dict):
                            # Try object of arrays or list inside key
                            try:
                                df = pd.DataFrame(raw_json)
                            except Exception:
                                # Look for first array value in dict
                                list_keys = [k for k, v in raw_json.items() if isinstance(v, list)]
                                if list_keys:
                                    df = pd.DataFrame(raw_json[list_keys[0]])
                                else:
                                    df = pd.DataFrame([raw_json])

                    table_name = sanitize_identifier(base_name, prefix_default="tbl")
                    cleaned_df, clean_to_orig, c_warns = clean_and_infer_dataframe(df)
                    file_warns.extend(c_warns)

                    if mode == "replace":
                        dest_conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                        dest_conn.execute("DELETE FROM _no2sql_metadata WHERE table_name = ?", (table_name,))

                    cleaned_df.to_sql(table_name, dest_conn, if_exists=mode, index=False)

                    for c in cleaned_df.columns:
                        dest_conn.execute(
                            """
                            INSERT OR REPLACE INTO _no2sql_metadata (table_name, clean_column, original_column, inferred_type)
                            VALUES (?, ?, ?, ?)
                            """,
                            (table_name, c, clean_to_orig.get(c, c), str(cleaned_df[c].dtype)),
                        )

                    all_created_tables.append({
                        "name": table_name,
                        "row_count": len(cleaned_df),
                        "columns": [{"name": c, "original_name": clean_to_orig.get(c, c), "type": str(cleaned_df[c].dtype)} for c in cleaned_df.columns],
                        "warnings": c_warns,
                    })
                    continue

                # 5. Parquet
                if ext == ".parquet":
                    df = pd.read_parquet(io.BytesIO(content_bytes))
                    table_name = sanitize_identifier(base_name, prefix_default="tbl")
                    cleaned_df, clean_to_orig, c_warns = clean_and_infer_dataframe(df)
                    file_warns.extend(c_warns)

                    if mode == "replace":
                        dest_conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                        dest_conn.execute("DELETE FROM _no2sql_metadata WHERE table_name = ?", (table_name,))

                    cleaned_df.to_sql(table_name, dest_conn, if_exists=mode, index=False)

                    for c in cleaned_df.columns:
                        dest_conn.execute(
                            """
                            INSERT OR REPLACE INTO _no2sql_metadata (table_name, clean_column, original_column, inferred_type)
                            VALUES (?, ?, ?, ?)
                            """,
                            (table_name, c, clean_to_orig.get(c, c), str(cleaned_df[c].dtype)),
                        )

                    all_created_tables.append({
                        "name": table_name,
                        "row_count": len(cleaned_df),
                        "columns": [{"name": c, "original_name": clean_to_orig.get(c, c), "type": str(cleaned_df[c].dtype)} for c in cleaned_df.columns],
                        "warnings": c_warns,
                    })
                    continue

                all_warnings.append(f"Unsupported file format for '{filename}'.")

            except Exception as e:
                logger.error(f"Error parsing file '{filename}': {e}", exc_info=True)
                all_warnings.append(f"Failed to process '{filename}': {str(e)}")

        dest_conn.commit()
        dest_conn.close()

        return {
            "tables": all_created_tables,
            "warnings": all_warnings,
        }

    def preview_table(self, table_name: str, limit: int = 10) -> Dict[str, Any]:
        """Safe read-only preview of first N rows from a table."""
        if not settings.is_database_present():
            raise FileNotFoundError("Workspace database is not loaded.")

        conn = self.get_connection(read_only=True)
        cur = conn.cursor()

        # Schema allow-list check
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_no2sql_%'"
        )
        allowed_tables = [r["name"] for r in cur.fetchall()]

        if table_name not in allowed_tables:
            conn.close()
            raise ValueError(f"Table '{table_name}' does not exist in workspace database.")

        cur.execute(f'SELECT * FROM "{table_name}" LIMIT {int(limit)}')
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
        conn.close()

        # Get original column name mappings
        col_mappings = self.get_column_mapping(table_name).get(table_name, {})

        return {
            "table_name": table_name,
            "columns": columns,
            "original_columns": [col_mappings.get(c, c) for c in columns],
            "rows": rows,
            "row_count": len(rows),
        }


data_service = DataService()
