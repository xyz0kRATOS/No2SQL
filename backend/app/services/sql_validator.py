"""
SQL Validator for No2SQL.
Uses sqlglot to perform AST-based validation:
- Strictly single SELECT (or CTE-SELECT / UNION of SELECTs)
- Forbids all DDL/DML, transactions, PRAGMA, ATTACH, etc.
- Enforces database schema allow-list
- Resolves table aliases for accurate column validation
- Prevents multi-statement chaining and obfuscated execution
"""

from typing import List, Dict, Any, Set, Tuple, Optional
import sqlglot
from sqlglot import exp, errors
from .schema_service import schema_service
from ..config import settings

FORBIDDEN_AST_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Command,
    exp.Pragma,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,
    exp.TruncateTable,
    exp.Merge,
    exp.Grant,
    exp.Revoke,
    exp.Attach,
    exp.Detach,
)

SYSTEM_TABLES_PREFIXES = ("sqlite_", "pg_", "information_schema")


class SQLValidator:
    def __init__(self, dialect: str = None):
        self.dialect = dialect or settings.SQL_DIALECT

    def validate(self, sql: str, allowed_tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Validates SQL string and returns validation result:
        {
            "allowed": bool,
            "reason": str,
            "tables": List[str],
            "columns": List[str]
        }
        """
        if not sql or not sql.strip():
            return {
                "allowed": False,
                "reason": "SQL query cannot be empty.",
                "tables": [],
                "columns": [],
            }

        cleaned_sql = sql.strip()

        if len(cleaned_sql) > 2000:
            return {
                "allowed": False,
                "reason": "SQL query exceeds maximum allowed length of 2000 characters.",
                "tables": [],
                "columns": [],
            }

        # Parse AST with sqlglot
        try:
            raw_stmts = sqlglot.parse(cleaned_sql, read=self.dialect)
        except errors.ParseError as pe:
            return {
                "allowed": False,
                "reason": f"SQL syntax error: {str(pe)}",
                "tables": [],
                "columns": [],
            }
        except Exception as ex:
            return {
                "allowed": False,
                "reason": f"Could not parse SQL: {str(ex)}",
                "tables": [],
                "columns": [],
            }

        statements = [s for s in raw_stmts if s is not None]

        if len(statements) == 0:
            return {
                "allowed": False,
                "reason": "No valid executable SQL statements found.",
                "tables": [],
                "columns": [],
            }

        if len(statements) > 1:
            return {
                "allowed": False,
                "reason": "Multiple SQL statements are not permitted (semicolon chaining detected).",
                "tables": [],
                "columns": [],
            }

        stmt = statements[0]

        # Root must be Select or Union of Selects
        if not isinstance(stmt, (exp.Select, exp.Union)):
            return {
                "allowed": False,
                "reason": f"Only read-only SELECT statements are allowed (found statement type: {stmt.key.upper()}).",
                "tables": [],
                "columns": [],
            }

        # Check for forbidden AST nodes anywhere in the tree
        for forbidden_cls in FORBIDDEN_AST_NODES:
            found_nodes = list(stmt.find_all(forbidden_cls))
            if found_nodes:
                op_name = forbidden_cls.__name__.upper()
                return {
                    "allowed": False,
                    "reason": f"Disallowed operation detected: {op_name}. Only read-only queries are permitted.",
                    "tables": [],
                    "columns": [],
                }

        # Extract CTE names so we don't treat them as physical tables
        cte_names: Set[str] = set()
        for cte in stmt.find_all(exp.CTE):
            alias = cte.alias_or_name
            if alias:
                cte_names.add(alias.lower())

        # Determine schema allowed tables
        if allowed_tables is None:
            allowed_tables = [t.lower() for t in schema_service.get_allowed_tables()]
        else:
            allowed_tables = [t.lower() for t in allowed_tables]

        # Map aliases to physical tables
        table_alias_map: Dict[str, str] = {}
        referenced_tables: Set[str] = set()

        for table_node in stmt.find_all(exp.Table):
            t_name = table_node.name
            if not t_name:
                continue
            lower_t_name = t_name.lower()

            # Record alias
            alias = table_node.alias
            if alias:
                table_alias_map[alias.lower()] = lower_t_name

            # Skip CTE aliases
            if lower_t_name in cte_names:
                continue

            # Check for system tables
            if lower_t_name == "sqlite_master" or lower_t_name.startswith(SYSTEM_TABLES_PREFIXES):
                return {
                    "allowed": False,
                    "reason": f"Access to internal or system table '{t_name}' is forbidden.",
                    "tables": [],
                    "columns": [],
                }

            # Check allow-list
            if allowed_tables and lower_t_name not in allowed_tables:
                return {
                    "allowed": False,
                    "reason": f"Table '{t_name}' is not in the allowed schema tables ({', '.join(allowed_tables)}).",
                    "tables": [],
                    "columns": [],
                }

            referenced_tables.add(lower_t_name)

        # Extract columns (best effort with alias resolution)
        table_cols_map = schema_service.get_table_columns_map()
        referenced_columns: Set[str] = set()

        for col_node in stmt.find_all(exp.Column):
            c_name = col_node.name
            t_name = col_node.table
            if not c_name or c_name == "*":
                continue

            if t_name:
                resolved_table = table_alias_map.get(t_name.lower(), t_name.lower())
                qualified = f"{resolved_table}.{c_name}"
                referenced_columns.add(qualified)

                # Validate column against schema if table is known
                if resolved_table in table_cols_map:
                    known_cols = [c.lower() for c in table_cols_map[resolved_table]]
                    if c_name.lower() not in known_cols:
                        return {
                            "allowed": False,
                            "reason": f"Column '{c_name}' does not exist on table '{resolved_table}'.",
                            "tables": sorted(list(referenced_tables)),
                            "columns": [],
                        }
            else:
                referenced_columns.add(c_name)

        return {
            "allowed": True,
            "reason": "Query passed AST validation and conforms to read-only schema rules.",
            "tables": sorted(list(referenced_tables)),
            "columns": sorted(list(referenced_columns)),
        }


# Singleton validator
sql_validator = SQLValidator()
