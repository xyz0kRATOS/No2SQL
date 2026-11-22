# No2SQL — "Ask your database any question in clear English"

**Course Project:** SCSE4041 — Prompt Engineering  
**Team:** Tech Goliaths  
**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Google Gemini (`google-genai`), SQLite, sqlglot, Pydantic v2, Vanilla HTML/CSS/JS

---

## 1. What It Is

**No2SQL** is a zero-dependency, locally-runnable natural language query engine that translates user questions into safe, verified SQL queries against **your own uploaded data**.

- **No Placeholder Data**: The app ships completely clean with zero pre-loaded, synthetic, or fake data. You supply your own files; No2SQL dynamically builds an isolated SQLite workspace database (`data/workspace.db`).
- **Real Google Gemini Integration**: Uses the official `google-genai` SDK with strict JSON schema outputs and low temperature (0.1). Never returns fake or canned answers.
- **Strict AST Security**: Every query is validated by `sqlglot` to permit strictly single `SELECT` / CTE-`SELECT` statements. DDL, DML, write operations, and system tables are rejected before execution.
- **Read-Only Defense-in-Depth**: Once the workspace database is built, it is opened in read-only mode (`file:...?mode=ro`, `uri=True`) with `PRAGMA query_only = ON`. Generating SQL never executes it; queries run only when you click "Run Query" via a secure opaque query token.

---

## 2. Architecture Diagram

```
+-----------------------------------------------------------------------------+
|                          Web Browser UI (Vanilla JS)                        |
|  - Drag & Drop Upload Zone             - Dynamic Schema Sidebar             |
|  - Real Gemini Status Badge            - Monospace SQL Highlighter          |
|  - AI-Generated Suggested Questions    - Client-Side CSV Export             |
+-----------------------------------------------------------------------------+
                                      |
         1. Upload Data Files         |  2. POST /api/query/generate
         (CSV, XLSX, JSON, SQLite)    |  (Question string)
                                      v
+-----------------------------------------------------------------------------+
|                        FastAPI Backend Server (Port 8000)                   |
|                                                                             |
|  +---------------------+      +---------------------+      +-------------+  |
|  | Data Ingestion      | ---> | Schema Service      | ---> | Gemini SDK  |  |
|  | - Type inference    |      | - Inferred joins    |      | (google-    |  |
|  | - Sanitizes names   |      | - Data profiling    |      |  genai)     |  |
|  +---------------------+      +---------------------+      +-------------+  |
|                                          |                                  |
|                                          v                                  |
|                             +--------------------------+                    |
|                             | sqlglot AST Validator    |                    |
|                             | - Only 1 SELECT stmt     |                    |
|                             | - Blocks DDL/DML/PRAGMA  |                    |
|                             | - Enforces Allow-List    |                    |
|                             +--------------------------+                    |
|                                          |                                  |
|                                          v                                  |
|                             +--------------------------+                    |
|                             | Token Store & Registry   |                    |
|                             +--------------------------+                    |
+-----------------------------------------------------------------------------+
                                      |
                      Re-validates token + PRAGMA query_only=ON
                                      v
+-----------------------------------------------------------------------------+
|              SQLite Workspace Database (data/workspace.db)                  |
|              - Dynamic user tables created from uploaded files              |
|              - Read-only connection for all user queries                    |
+-----------------------------------------------------------------------------+
```

---

## 3. Supported File Formats

You can upload one or multiple files simultaneously (drag-and-drop or file picker):

- **`.csv`, `.tsv`, `.txt`**: Auto-detects delimiters (`,`, `\t`, `;`, `|`) and encodings (`utf-8`, `utf-8-sig`, `latin-1`).
- **`.xlsx`, `.xls`**: **Each sheet becomes its own database table**. Empty sheets are safely skipped.
- **`.json`**: Array of objects or object of arrays.
- **`.jsonl`**: Newline-delimited JSON objects.
- **`.parquet`**: Ingests Apache Parquet tabular datasets.
- **`.db`, `.sqlite`, `.sqlite3`**: Imports all user tables from an existing SQLite database.

**Automatic Sanitisation**:
- Table names and column headers are normalized to `lower_snake_case` (e.g. `"Customer Name"` $\rightarrow$ `customer_name`).
- Currency symbols (`$`, `₹`, `€`, `£`) and thousand separators are cleanly parsed into numeric columns.
- Dates are converted to ISO `YYYY-MM-DD` strings so SQLite date functions (`date()`, `strftime()`) work seamlessly.
- Original column headers are preserved and displayed in tooltips and preview tables.

---

## 4. Quick Start (3 Steps)

### Step 1: Start the server

**On Windows:**
```cmd
run.bat
```

**On Linux / macOS:**
```bash
chmod +x run.sh
./run.sh
```

*(Or manual start: `python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload`)*

### Step 2: Add your Gemini API key

Open [.env](file:///C:/Users/amanp/.gemini/antigravity/scratch/no2sql/.env) in the project root and paste your key:

```env
GEMINI_API_KEY=AIzaSyYourActualKeyHere
```

*(Alternatively, click the **Settings (gear)** icon in the top-right of the web app to paste and test your key directly in the UI).*

### Step 3: Open the app & ask questions

1. Navigate to: **http://localhost:8000**
2. The header badge will show: `● Gemini: connected`
3. Drag and drop your spreadsheet or CSV file into the upload zone and click **Upload & Build Database**.
4. Click any of the AI-suggested question chips or type your own question in plain English!

---

## 5. Privacy & AI Data Sharing

No2SQL includes a **"Share sample values with the AI"** toggle in the Settings modal (default: ON):

> **Privacy Note:** When enabled, column names, inferred data types, and a few sample distinct values from low-cardinality columns (e.g. status values like `'Completed'`, `'Pending'`) are sent to Google Gemini to ensure generated SQL uses accurate filter strings. **Do not upload sensitive personal data you are not permitted to share.** When toggled OFF, only table and column names and types are sent.

---

## 6. How to Clear Data

- In the left sidebar under "Your Data", click the red **Clear All Data** button.
- Confirm the dialog to unlink `data/workspace.db` and reset the application to its clean, empty state.

---

## 7. How to Run Automated Tests

The automated test suite uses temporary in-memory fixtures (no pre-seeded database required):

```bash
cd backend
python -m pytest
```

Expected result:
```
======================== 26 passed, 1 skipped in 3.18s ========================
```
*(The 1 skipped test is an optional live Gemini integration test that runs when a live key is present in the environment).*

---

## 8. Live 5-Minute Demo Script (Evaluator Walkthrough)

1. **Clean Start (30s):**
   - Open `http://localhost:8000`. Point out the clean empty state: *"Upload your data to get started"*.
   - Point out the header badges: `No data loaded` and `Gemini: connected`.
2. **Data Ingestion (1 min):**
   - Drag in a sample CSV or multi-sheet Excel file.
   - Click **Upload & Build Database**. Show the success summary showing created tables and row counts.
   - Show the left sidebar updating with table names, row counts, and column types. Click **Preview First 10 Rows** on any table to show safe data inspection.
3. **AI-Suggested Questions (30s):**
   - Point out the dynamic question chips generated by Gemini specifically for the uploaded dataset's schema.
4. **Natural Language Query (1 min):**
   - Click a suggested question chip (e.g. *"Who are the top 5 customers by sales?"*).
   - Click **Generate SQL** (or press `Ctrl+Enter`).
   - Highlight that **generating SQL does not run it**. Show the green **Validated** banner, the plain-English explanation, referenced tables/columns, and highlighted SQL.
5. **Execution & Export (1 min):**
   - Click **Run Query**. Show the result table with row count and duration in milliseconds.
   - Click **Download CSV** to demonstrate instant client-side export.
6. **Safety Refusal & Ambiguity (1 min):**
   - Ask: *"Delete all records where amount is zero."* $\rightarrow$ The engine refuses the write operation with a friendly read-only message.
   - Ask an ambiguous question $\rightarrow$ The engine presents a clarification question with candidate column names.

---

## 9. Troubleshooting

- **"Gemini: key missing" (Red Badge)**:
  - Add your Gemini API key to `.env` (`GEMINI_API_KEY=AIzaSy...`) or click the gear icon in the top right to paste it into the Settings modal.
- **"Gemini: error" (Amber Badge) / 403 Forbidden**:
  - Verify your API key has access to the Gemini API in Google AI Studio.
- **Rate Limit / 429 Quota Exceeded**:
  - The backend automatically backs off and retries on 429 errors. Wait 10-15 seconds before submitting another query.
- **Excel Date Parsing**:
  - If date columns in Excel contain mixed formats, No2SQL attempts ISO formatting automatically. For best results, format date columns in Excel as Standard Dates before uploading.
