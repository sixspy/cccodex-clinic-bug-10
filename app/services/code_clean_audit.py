"""编码清洗读轨审计：只留甲路切流账册单侧引用。"""
from __future__ import annotations

from app.db import get_db
from app.services.code_clean_cutover import board as cutover_board


def audit_list(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            ("code_clean_evt_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def audit_summary(db_path: str | None = None) -> dict:
    return {
        "title": "编码清洗审计",
        "events": audit_list(db_path),
        "cutover": cutover_board(db_path),
    }
