"""
Tests for AST-based SQL Validator (sqlglot).
Verifies read-only constraints, syntax edge cases, injection attempts, and schema allow-lists.
"""

import pytest
from app.services.sql_validator import SQLValidator

ALLOWED_TABLES = ["customers", "categories", "products", "orders", "order_items"]


@pytest.fixture
def validator():
    return SQLValidator(dialect="sqlite")


def test_valid_select(validator):
    sql = "SELECT customer_id, name, city FROM customers WHERE city = 'Delhi' LIMIT 10"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is True
    assert "customers" in res["tables"]


def test_valid_cte_select(validator):
    sql = """
    WITH customer_orders AS (
        SELECT customer_id, COUNT(*) as ord_count
        FROM orders
        GROUP BY customer_id
    )
    SELECT c.name, co.ord_count
    FROM customers c
    JOIN customer_orders co ON c.customer_id = co.customer_id
    """
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is True
    assert "customers" in res["tables"]
    assert "orders" in res["tables"]
    # CTE itself should not be flagged as an invalid table
    assert "customer_orders" not in res["tables"]


def test_reject_drop_table(validator):
    sql = "DROP TABLE customers;"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "DROP" in res["reason"] or "read-only" in res["reason"].lower()


def test_reject_delete_from(validator):
    sql = "DELETE FROM orders WHERE order_id = 1"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "DELETE" in res["reason"] or "read-only" in res["reason"].lower()


def test_reject_update(validator):
    sql = "UPDATE customers SET city = 'Mumbai' WHERE customer_id = 1"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "UPDATE" in res["reason"] or "read-only" in res["reason"].lower()


def test_reject_insert(validator):
    sql = "INSERT INTO categories (category_name) VALUES ('Hacking')"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "INSERT" in res["reason"] or "read-only" in res["reason"].lower()


def test_reject_multiple_statements(validator):
    sql = "SELECT * FROM customers; DELETE FROM customers;"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "Multiple SQL statements" in res["reason"] or "semicolon" in res["reason"].lower()


def test_reject_select_into(validator):
    sql = "SELECT * INTO backup_customers FROM customers"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False


def test_reject_pragma(validator):
    sql = "PRAGMA table_info(customers)"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "PRAGMA" in res["reason"] or "read-only" in res["reason"].lower()


def test_reject_attach(validator):
    sql = "ATTACH DATABASE 'malicious.db' AS mal"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False


def test_reject_unknown_table(validator):
    sql = "SELECT * FROM employees"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "not in the allowed schema tables" in res["reason"]


def test_reject_sqlite_master(validator):
    sql = "SELECT sql FROM sqlite_master WHERE type='table'"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "system table" in res["reason"].lower() or "forbidden" in res["reason"].lower()


def test_reject_empty_input(validator):
    assert validator.validate("", allowed_tables=ALLOWED_TABLES)["allowed"] is False
    assert validator.validate("   ", allowed_tables=ALLOWED_TABLES)["allowed"] is False


def test_reject_comment_obfuscated_drop(validator):
    sql = "/* comment */ DROP TABLE customers"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False


def test_reject_broken_token_obfuscation(validator):
    sql = "SEL/**/ECT * FROM customers"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "syntax error" in res["reason"].lower()


def test_reject_over_long_query(validator):
    sql = "SELECT * FROM customers WHERE " + ("1 = 1 AND " * 400) + "1 = 1"
    res = validator.validate(sql, allowed_tables=ALLOWED_TABLES)
    assert res["allowed"] is False
    assert "exceeds maximum allowed length" in res["reason"]
