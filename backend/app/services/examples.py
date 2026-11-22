"""
Schema-Agnostic Few-Shot Patterns for No2SQL.
Used in prompt engineering to teach the LLM structural SQL patterns,
explicitly marked as illustrative placeholders so the model never hallucinates
these table or column names on user data.
"""

from typing import List, Dict, Any

SCHEMA_AGNOSTIC_EXAMPLES: List[Dict[str, Any]] = [
    {
        "question": "Who are the top 5 contributors by total contribution amount?",
        "status": "ok",
        "sql": """
SELECT contributor_id, name, ROUND(SUM(amount), 2) AS total_contributions
FROM sample_contributors
GROUP BY contributor_id, name
ORDER BY total_contributions DESC
LIMIT 5;
""".strip(),
        "explanation": "Calculates the total contribution amount per contributor and returns the top 5 highest contributors.",
        "tables_used": ["sample_contributors"],
        "columns_used": ["sample_contributors.contributor_id", "sample_contributors.name", "sample_contributors.amount"],
        "assumptions": ["Aggregates sum of amount grouped by contributor."],
        "clarification_question": None,
    },
    {
        "question": "Show total sales volume grouped by region with customer details.",
        "status": "ok",
        "sql": """
SELECT r.region_name, COUNT(t.transaction_id) AS transaction_count, ROUND(SUM(t.sale_amount), 2) AS total_sales
FROM sample_regions r
JOIN sample_transactions t ON r.region_id = t.region_id
GROUP BY r.region_id, r.region_name
ORDER BY total_sales DESC;
""".strip(),
        "explanation": "Joins regions and transactions tables on region_id and aggregates total sales and transaction count per region.",
        "tables_used": ["sample_regions", "sample_transactions"],
        "columns_used": ["sample_regions.region_id", "sample_regions.region_name", "sample_transactions.transaction_id", "sample_transactions.sale_amount", "sample_transactions.region_id"],
        "assumptions": ["Groups results by region identifier and name."],
        "clarification_question": None,
    },
    {
        "question": "List all active records created within the last 30 days.",
        "status": "ok",
        "sql": """
SELECT item_id, item_title, created_date, status
FROM sample_items
WHERE status = 'Active'
  AND created_date >= date('now', '-30 days')
ORDER BY created_date DESC;
""".strip(),
        "explanation": "Filters for records where status matches 'Active' and creation date is within the trailing 30 days.",
        "tables_used": ["sample_items"],
        "columns_used": ["sample_items.item_id", "sample_items.item_title", "sample_items.created_date", "sample_items.status"],
        "assumptions": ["Uses SQLite date math date('now', '-30 days') for relative date filtering."],
        "clarification_question": None,
    },
    {
        "question": "Find users who have never performed any activity.",
        "status": "ok",
        "sql": """
SELECT u.user_id, u.user_name, u.email
FROM sample_users u
LEFT JOIN sample_activity_logs a ON u.user_id = a.user_id
WHERE a.activity_id IS NULL;
""".strip(),
        "explanation": "Uses a LEFT JOIN with an IS NULL condition to return users who have zero corresponding entries in activity logs.",
        "tables_used": ["sample_users", "sample_activity_logs"],
        "columns_used": ["sample_users.user_id", "sample_users.user_name", "sample_users.email", "sample_activity_logs.user_id", "sample_activity_logs.activity_id"],
        "assumptions": ["Users with no matching foreign key in activity logs are considered inactive."],
        "clarification_question": None,
    },
    {
        "question": "Delete all expired records from the archive table.",
        "status": "unsupported",
        "sql": None,
        "explanation": "No2SQL is a strictly read-only analytical query engine. Modifying, deleting, or altering database records is prohibited.",
        "tables_used": [],
        "columns_used": [],
        "assumptions": ["Write, delete, and DDL actions are blocked by security policy."],
        "clarification_question": None,
    },
]
