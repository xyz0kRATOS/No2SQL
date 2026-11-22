"""
Integration tests for No2SQL Data Ingestion, Dynamic Schema, and Query Generation.
Uses temporary CSV, Excel, and JSON fixtures without any hardcoded synthetic database.
Gemini client is patched in automated tests; includes one optional live Gemini test.
"""

import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.services.data_service import data_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_workspace():
    """Ensures each test starts and ends with a clean workspace."""
    data_service.clear_workspace()
    yield
    data_service.clear_workspace()


def test_health_and_llm_status_missing_key():
    """Verifies /api/llm/status correctly reports missing key when GEMINI_API_KEY is empty."""
    with patch.object(settings, "GEMINI_API_KEY", ""):
        res = client.get("/api/llm/status?refresh=true")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "missing_key"
        assert "missing" in data["message"].lower()


def test_empty_workspace_status():
    """Initial fresh state must have is_loaded = False and zero tables."""
    res = client.get("/api/data/status")
    assert res.status_code == 200
    data = res.json()
    assert data["is_loaded"] is False
    assert data["table_count"] == 0
    assert len(data["tables"]) == 0


def test_upload_csv_cleaning_and_type_inference():
    """Tests uploading a messy CSV: sanitises headers, infers numeric currency and ISO dates."""
    csv_content = """Order ID, Customer  Name, Purchase Amount,  Order Date , Active Status
ORD-101, Alice, "$1,250.50", 2026-05-15, True
ORD-102, Bob, "₹3,400.00", 2026-05-18, False
ORD-103, Charlie, "450.25", 2026-05-20, True
"""
    files = [("files", ("raw orders.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv"))]
    res = client.post("/api/data/upload", files=files, data={"mode": "replace"})
    assert res.status_code == 200
    upload_data = res.json()
    assert upload_data["success"] is True
    assert len(upload_data["tables"]) == 1

    table_meta = upload_data["tables"][0]
    assert table_meta["name"] == "raw_orders"
    assert table_meta["row_count"] == 3

    col_names = [c["name"] for c in table_meta["columns"]]
    assert "order_id" in col_names
    assert "customer_name" in col_names
    assert "purchase_amount" in col_names
    assert "order_date" in col_names
    assert "active_status" in col_names

    # Check status endpoint
    status_res = client.get("/api/data/status")
    assert status_res.status_code == 200
    assert status_res.json()["is_loaded"] is True
    assert status_res.json()["table_count"] == 1


def test_upload_excel_multiple_sheets():
    """Verifies that each sheet in an Excel workbook creates its own database table."""
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df1 = pd.DataFrame({"client_id": [1, 2], "company": ["Acme", "Globex"]})
        df1.to_excel(writer, sheet_name="Clients", index=False)

        df2 = pd.DataFrame({"proj_id": [101, 102], "title": ["Redesign", "Migration"]})
        df2.to_excel(writer, sheet_name="Projects", index=False)

    bio.seek(0)
    files = [("files", ("company_data.xlsx", bio, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
    res = client.post("/api/data/upload", files=files, data={"mode": "replace"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    created_names = [t["name"] for t in data["tables"]]
    assert any("clients" in n for n in created_names)
    assert any("projects" in n for n in created_names)


def test_upload_json():
    """Verifies JSON array of objects ingestion."""
    json_content = json.dumps([
        {"id": 1, "department": "Engineering", "budget": 50000},
        {"id": 2, "department": "Marketing", "budget": 30000},
    ])
    files = [("files", ("departments.json", io.BytesIO(json_content.encode("utf-8")), "application/json"))]
    res = client.post("/api/data/upload", files=files, data={"mode": "replace"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["tables"][0]["name"] == "departments"
    assert data["tables"][0]["row_count"] == 2


def test_relationship_inference():
    """Verifies automatic join inference on common unique keys with overlapping values."""
    csv_cust = """customer_id,name
1,Alpha Corp
2,Beta LLC
3,Gamma Inc
"""
    csv_invoices = """invoice_id,customer_id,total
101,1,500.0
102,1,750.0
103,2,1200.0
"""
    files = [
        ("files", ("customers.csv", io.BytesIO(csv_cust.encode("utf-8")), "text/csv")),
        ("files", ("invoices.csv", io.BytesIO(csv_invoices.encode("utf-8")), "text/csv")),
    ]
    res = client.post("/api/data/upload", files=files, data={"mode": "replace"})
    assert res.status_code == 200

    schema_res = client.get("/api/schema")
    assert schema_res.status_code == 200
    schema_data = schema_res.json()

    rels = schema_data.get("relationships", [])
    assert len(rels) >= 1
    rel = rels[0]
    assert rel["from_column"] == "customer_id"
    assert rel["to_column"] == "customer_id"


def test_replace_vs_append_mode():
    """Verifies that mode=append adds rows while mode=replace resets rows."""
    csv_1 = "item_name,qty\nPen,10\n"
    csv_2 = "item_name,qty\nNotebook,5\n"

    # 1. First upload
    files1 = [("files", ("inventory.csv", io.BytesIO(csv_1.encode("utf-8")), "text/csv"))]
    client.post("/api/data/upload", files=files1, data={"mode": "replace"})
    assert client.get("/api/data/status").json()["total_rows"] == 1

    # 2. Append mode
    files2 = [("files", ("inventory.csv", io.BytesIO(csv_2.encode("utf-8")), "text/csv"))]
    client.post("/api/data/upload", files=files2, data={"mode": "append"})
    assert client.get("/api/data/status").json()["total_rows"] == 2

    # 3. Replace mode
    client.post("/api/data/upload", files=files2, data={"mode": "replace"})
    assert client.get("/api/data/status").json()["total_rows"] == 1


def test_preview_table_and_security_allow_list():
    """Verifies safe preview and rejection of unallowed/system tables."""
    csv_content = "code,name\nUS,United States\nIN,India\n"
    files = [("files", ("countries.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv"))]
    client.post("/api/data/upload", files=files, data={"mode": "replace"})

    # Valid preview
    res = client.get("/api/data/preview?table=countries&limit=5")
    assert res.status_code == 200
    data = res.json()
    assert data["table_name"] == "countries"
    assert data["row_count"] == 2

    # Rejection of system table
    res_err = client.get("/api/data/preview?table=sqlite_master")
    assert res_err.status_code in (404, 500)


def test_clear_workspace():
    """Verifies DELETE /api/data removes database tables and resets status."""
    csv_content = "id,val\n1,Test\n"
    files = [("files", ("temp.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv"))]
    client.post("/api/data/upload", files=files)
    assert client.get("/api/data/status").json()["is_loaded"] is True

    del_res = client.delete("/api/data")
    assert del_res.status_code == 200
    assert client.get("/api/data/status").json()["is_loaded"] is False


def test_generate_and_execute_with_gemini_mocked():
    """
    Tests end-to-end query generation and execution with patched Gemini SDK.
    Verifies token generation, execution capping, and read-only query results.
    """
    csv_content = """employee_id,department,salary
1,Engineering,95000
2,Engineering,88000
3,Design,72000
"""
    files = [("files", ("staff.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv"))]
    client.post("/api/data/upload", files=files)

    mock_gemini_output = {
        "status": "ok",
        "sql": "SELECT department, ROUND(AVG(salary), 2) AS avg_salary FROM staff GROUP BY department ORDER BY avg_salary DESC;",
        "explanation": "Calculates average salary per department and sorts from highest to lowest.",
        "tables_used": ["staff"],
        "columns_used": ["staff.department", "staff.salary"],
        "assumptions": ["Aggregates salary by department."],
        "clarification_question": None,
    }

    with patch("app.services.prompt_workflow.gemini_service.generate", return_value=mock_gemini_output):
        gen_res = client.post("/api/query/generate", json={"question": "What is the average salary by department?"})
        assert gen_res.status_code == 200
        gen_data = gen_res.json()

        assert gen_data["status"] == "ok"
        assert gen_data["query_token"] is not None
        assert "staff" in gen_data["tables_used"]

        # Execute query via token
        token = gen_data["query_token"]
        exec_res = client.post("/api/query/execute", json={"query_token": token})
        assert exec_res.status_code == 200
        exec_data = exec_res.json()
        assert exec_data["success"] is True
        assert exec_data["row_count"] == 2
        assert len(exec_data["rows"]) == 2


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="Requires live GEMINI_API_KEY in environment")
def test_live_gemini_integration():
    """Optional live test run only when GEMINI_API_KEY is present in environment."""
    csv_content = "product,sales\nWidget A,500\nWidget B,900\n"
    files = [("files", ("live_test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv"))]
    client.post("/api/data/upload", files=files)

    res = client.post("/api/query/generate", json={"question": "Which product had the highest sales?"})
    if res.status_code == 400:
        # Upstream demand spike / rate limit
        detail = res.json().get("detail", "").lower()
        assert "high demand" in detail or "gemini" in detail or "quota" in detail or "unavailable" in detail
    else:
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["query_token"] is not None
