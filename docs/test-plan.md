# No2SQL Test Plan & Verification Matrix

Course Project: **SCSE4041 - Prompt Engineering**  
Team: **Tech Goliaths**  
Prototype: **No2SQL** ("Ask your database any question in clear English")

---

## 1. Quality Tenets & Architecture Verification

1. **User-Supplied Data Model**: No canned, fake, or synthetic placeholder data is ever loaded. The app starts empty and builds an isolated, dynamic workspace database (`data/workspace.db`) on demand from user uploads (.csv, .tsv, .xlsx, .xls, .json, .jsonl, .parquet, .db).
2. **Real Gemini Integration**: Official `google-genai` SDK with structured JSON schemas, dynamic Flash model resolution, and automatic self-repair turns on syntax or schema errors.
3. **AST-Enforced Defense-in-Depth**: Every generated SQL query must be a strictly single read-only `SELECT` / CTE-`SELECT`. All DDL/DML, injections, multi-statement chaining, and system table accesses are blocked by `sqlglot`.
4. **Read-Only Engine Isolation**: Workspace database is queried exclusively via SQLite read-only mode (`file:...mode=ro`, `uri=True`) with `PRAGMA query_only = ON`, opcode timeouts, and token-based execution.

---

## 2. Ingestion & Dynamic Schema Test Suite

| Test Identifier | Test Target | Vector / Conditions | Expected Behavior | Automated Result |
| :--- | :--- | :--- | :--- | :--- |
| **TC-DATA-01** | Empty Workspace Initialization | Fresh startup | `is_loaded: false`, 0 tables, empty state banner displayed. | **PASS** |
| **TC-DATA-02** | Messy CSV Ingestion | Uppercase, spaces, currency symbols (`$`, `₹`), ISO dates | Clean identifiers created (`lower_snake_case`), numbers & dates parsed. | **PASS** |
| **TC-DATA-03** | Excel Multi-Sheet Ingestion | `.xlsx` with multiple sheets ("Clients", "Projects") | Each sheet becomes a distinct table; empty sheets skipped. | **PASS** |
| **TC-DATA-04** | JSON Ingestion | `.json` array of objects | Normalized into structured table with inferred types. | **PASS** |
| **TC-DATA-05** | Relationship Inference | Two tables with matching `customer_id` and $\ge 80\%$ value overlap | Discovered as "inferred join" in schema context. | **PASS** |
| **TC-DATA-06** | Ingestion Modes | `mode=append` vs `mode=replace` | `append` adds rows; `replace` drops and recreates table. | **PASS** |
| **TC-DATA-07** | Preview Endpoint Allow-list | `GET /api/data/preview?table=...` | Returns first 10 rows for user tables; rejects `sqlite_master`. | **PASS** |
| **TC-DATA-08** | Workspace Clearing | `DELETE /api/data` | Database unlinked, schema and status reset to empty. | **PASS** |

---

## 3. SQL Validator Security Verification (16 Vectors)

| Test ID | Input Query | Security Policy Rule | Result |
| :--- | :--- | :--- | :--- |
| **TC-SEC-01** | `SELECT ... FROM table LIMIT 10` | Valid SELECT query | **ALLOWED** |
| **TC-SEC-02** | `WITH cte AS (...) SELECT ...` | Valid CTE SELECT | **ALLOWED** |
| **TC-SEC-03** | `DROP TABLE table;` | Block DDL Drop | **REJECTED** |
| **TC-SEC-04** | `DELETE FROM table WHERE ...` | Block DML Delete | **REJECTED** |
| **TC-SEC-05** | `UPDATE table SET ...` | Block DML Update | **REJECTED** |
| **TC-SEC-06** | `INSERT INTO table VALUES (...)` | Block DML Insert | **REJECTED** |
| **TC-SEC-07** | `SELECT ...; DELETE FROM ...;` | Block Semicolon Chaining | **REJECTED** |
| **TC-SEC-08** | `SELECT * INTO backup FROM ...` | Block SELECT INTO | **REJECTED** |
| **TC-SEC-09** | `PRAGMA table_info(...)` | Block PRAGMA statements | **REJECTED** |
| **TC-SEC-10** | `ATTACH DATABASE 'evil.db'` | Block ATTACH statements | **REJECTED** |
| **TC-SEC-11** | `SELECT * FROM unknown_table` | Enforce Schema Allow-List | **REJECTED** |
| **TC-SEC-12** | `SELECT sql FROM sqlite_master` | Block SQLite system tables | **REJECTED** |
| **TC-SEC-13** | Empty input / whitespace | Reject empty queries | **REJECTED** |
| **TC-SEC-14** | `/* comment */ DROP TABLE ...` | Reject obfuscated commands | **REJECTED** |
| **TC-SEC-15** | `SEL/**/ECT * FROM table` | Catch broken token syntax errors | **REJECTED** |
| **TC-SEC-16** | SQL query > 2000 chars | Enforce maximum length limit | **REJECTED** |

---

## 4. Query Workflow & Execution Tests

| Test ID | Scenario | Behavior | Result |
| :--- | :--- | :--- | :--- |
| **TC-EXEC-01** | Unauthenticated Status | `GEMINI_API_KEY=""` $\rightarrow$ reports `status: "missing_key"` | **PASS** |
| **TC-EXEC-02** | Query Token Generation | Valid question produces opaque UUID `query_token` without running query | **PASS** |
| **TC-EXEC-03** | Token-Based Execution | `/api/query/execute` runs query read-only via token; rejects raw SQL | **PASS** |
| **TC-EXEC-04** | Execution Capping | Results capped at `MAX_RESULT_ROWS` (default 200) with truncation badge | **PASS** |
| **TC-EXEC-05** | Destructive Refusal | Requests to delete/alter records return `status="unsupported"` | **PASS** |
