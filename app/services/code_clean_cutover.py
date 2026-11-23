"""编码清洗切流账册：落点即钉旁路账册凭证，锁当刻指纹并拒回刷。"""
from __future__ import annotations

from app.db import get_db
from app.services.code_clean import (
    active_read_ref,
    cutover_fp,
    dashboard,
    land_cutover,
    panel_chip,
    reject_refresh,
    truth_flag,
)

_SLUG = "code_clean"
_TITLE = "编码清洗"


def append_cutover(ref_id: int, note: str, db_path: str | None = None) -> dict:
    """账册凭证落点：与落台同一把锁，落定后重复写直接 409。"""
    res = land_cutover(note=f"账册凭证 ref={ref_id} {note}", payload={"ref_id": ref_id}, db_path=db_path)
    return {
        "ref_id": ref_id,
        "note": note,
        "panel": panel_chip(db_path),
        "truth": truth_flag(db_path),
        "active_read": active_read_ref(db_path),
        "cutover_fp": cutover_fp(db_path),
        "reject_refresh": reject_refresh(db_path),
        "message": res["message"],
    }


def cutover_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_cutover_%",),
        ).fetchall()
        return [
            {
                "key": r["key"],
                "value": r["value"],
                "chip": panel_chip(db_path),
                "active_read": active_read_ref(db_path),
            }
            for r in rows
        ]


def board(db_path: str | None = None) -> dict:
    dash = dashboard(db_path)
    dash["cutover"] = cutover_rows(db_path)
    dash["fate"] = "cutover_book"
    return dash
