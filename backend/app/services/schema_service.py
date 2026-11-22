"""
Dynamic Schema Service for No2SQL.
Inspects the user's workspace database dynamically with zero hardcoded schemas.
Computes comprehensive data profiles (null %, distinct counts, min/max, low-cardinality sample values)
and infers relationships across tables based on key matching and value overlaps.
"""

import sqlite3
from typing import Dict, List, Any, Optional, Set
from ..config import settings
from .data_service import data_service


class SchemaService:
    def __init__(self):
        pass

    def get_connection(self) -> sqlite3.Connection:
        return data_service.get_connection(read_only=True)

    def get_allowed_tables(self) -> List[str]:
        if not settings.is_database_present():
            return []
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_no2sql_%' ORDER BY name"
            )
            tables = [r["name"] for r in cur.fetchall()]
            conn.close()
            return tables
        except Exception:
            return []

    def get_table_columns_map(self) -> Dict[str, List[str]]:
        if not settings.is_database_present():
            return {}
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_no2sql_%'"
            )
            tables = [r["name"] for r in cur.fetchall()]
            result = {}
            for t in tables:
                cur.execute(f'PRAGMA table_info("{t}")')
                result[t.lower()] = [c["name"].lower() for c in cur.fetchall()]
            conn.close()
            return result
        except Exception:
            return {}

    def inspect_schema(self, include_profiles: bool = True) -> Dict[str, Any]:
        """
        Dynamically inspects tables, columns, data profiles, and inferred relationships
        from the active workspace database.
        """
        if not settings.is_database_present():
            return {
                "dialect": settings.SQL_DIALECT,
                "database_name": "workspace.db",
                "is_loaded": False,
                "tables": {},
                "relationships": [],
                "allowed_tables": [],
            }

        conn = self.get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_no2sql_%' ORDER BY name"
        )
        table_names = [r["name"] for r in cur.fetchall()]

        # Column mappings (clean -> original)
        col_mappings = data_service.get_column_mapping()

        tables_data = {}
        for t_name in table_names:
            # Row count
            cur.execute(f'SELECT COUNT(*) as count FROM "{t_name}"')
            row_count = cur.fetchone()["count"]

            cur.execute(f'PRAGMA table_info("{t_name}")')
            cols_info = cur.fetchall()

            columns = []
            pk_columns = []
            t_col_maps = col_mappings.get(t_name, {})

            for col in cols_info:
                cname = col["name"]
                ctype = col["type"]
                pk = bool(col["pk"])
                if pk:
                    pk_columns.append(cname)

                col_meta = {
                    "name": cname,
                    "original_name": t_col_maps.get(cname, cname),
                    "type": ctype,
                    "primary_key": pk,
                    "nullable": not bool(col["notnull"]),
                }

                # Column profile
                if include_profiles and row_count > 0:
                    try:
                        cur.execute(f'SELECT COUNT("{cname}") as non_null, COUNT(DISTINCT "{cname}") as distinct_cnt FROM "{t_name}"')
                        row_stats = cur.fetchone()
                        non_null = row_stats["non_null"]
                        distinct_cnt = row_stats["distinct_cnt"]

                        null_pct = round(((row_count - non_null) / row_count) * 100, 1)
                        col_meta["null_percentage"] = null_pct
                        col_meta["distinct_count"] = distinct_cnt

                        # Min / Max for numeric / date
                        if "int" in ctype.lower() or "real" in ctype.lower() or "date" in ctype.lower() or "time" in ctype.lower():
                            cur.execute(f'SELECT MIN("{cname}") as min_val, MAX("{cname}") as max_val FROM "{t_name}" WHERE "{cname}" IS NOT NULL')
                            min_max = cur.fetchone()
                            if min_max:
                                col_meta["min_value"] = min_max["min_val"]
                                col_meta["max_value"] = min_max["max_val"]

                        # Sample values for low-cardinality text columns (<= 30 distinct values)
                        if distinct_cnt <= 30 and distinct_cnt > 0:
                            cur.execute(f'SELECT DISTINCT "{cname}" FROM "{t_name}" WHERE "{cname}" IS NOT NULL LIMIT 5')
                            col_meta["sample_values"] = [r[0] for r in cur.fetchall()]
                    except Exception:
                        pass

                columns.append(col_meta)

            tables_data[t_name] = {
                "name": t_name,
                "row_count": row_count,
                "primary_keys": pk_columns,
                "columns": columns,
            }

        # Infer relationships across tables
        relationships = self._infer_relationships(cur, tables_data)

        conn.close()

        return {
            "dialect": settings.SQL_DIALECT,
            "database_name": "workspace.db",
            "is_loaded": len(tables_data) > 0,
            "tables": tables_data,
            "relationships": relationships,
            "allowed_tables": list(tables_data.keys()),
        }

    def _infer_relationships(self, cur: sqlite3.Cursor, tables_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Infers joins across tables:
        Columns with matching names across tables where one side is (nearly) unique (>=95% unique)
        and values overlap >= 80%.
        """
        table_names = list(tables_data.keys())
        inferred = []

        for i in range(len(table_names)):
            for j in range(i + 1, len(table_names)):
                t1 = table_names[i]
                t2 = table_names[j]

                cols1 = {c["name"] for c in tables_data[t1]["columns"]}
                cols2 = {c["name"] for c in tables_data[t2]["columns"]}
                common_cols = cols1 & cols2

                for col in common_cols:
                    # Skip common generic columns that aren't IDs/keys (e.g. 'status', 'created_at', 'type', 'notes')
                    if col in ("status", "notes", "description", "name", "comment", "flag", "date", "created_at", "updated_at"):
                        continue

                    # Check uniqueness on both sides
                    try:
                        cur.execute(f'SELECT COUNT("{col}"), COUNT(DISTINCT "{col}") FROM "{t1}" WHERE "{col}" IS NOT NULL')
                        c1_total, c1_distinct = cur.fetchone()
                        cur.execute(f'SELECT COUNT("{col}"), COUNT(DISTINCT "{col}") FROM "{t2}" WHERE "{col}" IS NOT NULL')
                        c2_total, c2_distinct = cur.fetchone()

                        if c1_total == 0 or c2_total == 0:
                            continue

                        u1_ratio = c1_distinct / c1_total
                        u2_ratio = c2_distinct / c2_total

                        # One side must be nearly unique (>= 0.95)
                        if u1_ratio < 0.95 and u2_ratio < 0.95:
                            continue

                        # Check value overlap
                        cur.execute(f"""
                            SELECT COUNT(*) FROM (
                                SELECT DISTINCT "{col}" FROM "{t1}" WHERE "{col}" IS NOT NULL
                                INTERSECT
                                SELECT DISTINCT "{col}" FROM "{t2}" WHERE "{col}" IS NOT NULL
                            )
                        """)
                        overlap_count = cur.fetchone()[0]
                        min_distinct = min(c1_distinct, c2_distinct)

                        if min_distinct > 0 and (overlap_count / min_distinct) >= 0.80:
                            parent = t1 if u1_ratio >= u2_ratio else t2
                            child = t2 if parent == t1 else t1
                            inferred.append({
                                "from_table": child,
                                "from_column": col,
                                "to_table": parent,
                                "to_column": col,
                                "inferred": True,
                                "description": f"Inferred join on common key '{col}' ({int(overlap_count / min_distinct * 100)}% value overlap)",
                            })
                    except Exception:
                        continue

        return inferred

    def format_schema_for_prompt(self, share_sample_values: Optional[bool] = None) -> str:
        """
        Formats the dynamic schema and profile context for injection into the Gemini prompt.
        Respects the privacy toggle (share_sample_values).
        """
        if share_sample_values is None:
            share_sample_values = settings.SHARE_SAMPLE_VALUES

        schema = self.inspect_schema(include_profiles=True)
        if not schema["is_loaded"]:
            return "No tables or data have been loaded into the workspace yet."

        lines = [
            f"ACTIVE WORKSPACE DATABASE SCHEMA ({schema['dialect'].upper()} dialect):",
            "The database contains the following user-uploaded tables and profiles:\n",
        ]

        for tbl_name, tbl_info in schema["tables"].items():
            lines.append(f"Table: \"{tbl_name}\" (Total rows: {tbl_info['row_count']})")
            lines.append("  Columns:")
            for col in tbl_info["columns"]:
                pk_marker = " [PRIMARY KEY]" if col.get("primary_key") else ""
                orig_hint = f" (Original header: '{col['original_name']}')" if col['original_name'] != col['name'] else ""
                type_str = f" ({col['type']})" if col.get('type') else ""

                details = []
                if "null_percentage" in col and col["null_percentage"] > 0:
                    details.append(f"{col['null_percentage']}% null")
                if "distinct_count" in col:
                    details.append(f"{col['distinct_count']} distinct")

                # Numeric or date ranges
                if "min_value" in col and "max_value" in col and col["min_value"] is not None:
                    details.append(f"range: [{col['min_value']} to {col['max_value']}]")

                # Sample values if permitted
                if share_sample_values and "sample_values" in col and col["sample_values"]:
                    samples_repr = ", ".join(repr(s) for s in col["sample_values"][:5])
                    details.append(f"sample values: [{samples_repr}]")

                meta_line = f" - {', '.join(details)}" if details else ""
                lines.append(f"    - \"{col['name']}\"{type_str}{pk_marker}{orig_hint}{meta_line}")
            lines.append("")

        if schema["relationships"]:
            lines.append("INFERRED RELATIONSHIPS / JOINS:")
            for rel in schema["relationships"]:
                lines.append(f"  - \"{rel['from_table']}\".\"{rel['from_column']}\" -> \"{rel['to_table']}\".\"{rel['to_column']}\" ({rel['description']})")
            lines.append("")

        return "\n".join(lines)


schema_service = SchemaService()
