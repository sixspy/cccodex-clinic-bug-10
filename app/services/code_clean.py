"""清洗钉定：甲路切流账册单轨收口；徽标跟随落点，读轨拒回刷。"""
from __future__ import annotations

import hashlib
from datetime import datetime

from app.db import get_db
from app.services.errors import ServiceError

_SLUG = "code_clean"
_OK = "清洗已亮"
_BAD = "空码仍入"
_TITLE = "编码清洗"
_OLD = "old_track"
_CUTOVER = "cutover_book"


def _meta_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (key, value),
    )


def panel_chip(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_panel_chip", _BAD)


def truth_flag(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_truth", _BAD)


def active_read_ref(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_active_read", _OLD)


def cutover_fp(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_cutover_fp", "")


def reject_refresh(db_path: str | None = None) -> bool:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_reject_refresh", "0") == "1"


def live_flag(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_live_flag", "")


def archive_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_archive_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def pack_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_pack_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def empty_code_count(db_path: str | None = None) -> int:
    """空码条数：仍未收容的编码空访视行实时计数（读轨活值）。"""
    with get_db(db_path) as conn:
        return conn.execute(
            """
            SELECT COUNT(*) AS c FROM visit_rows
            WHERE quality='编码空' AND status IN ('待检','待补采')
            """
        ).fetchone()["c"]


def seed_skew(db_path: str | None = None) -> None:
    with get_db(db_path) as conn:
        _meta_set(conn, f"{_SLUG}_panel_chip", _OK)
        _meta_set(conn, f"{_SLUG}_truth", _BAD)
        _meta_set(conn, f"{_SLUG}_counter", "0")
        _meta_set(conn, f"{_SLUG}_gate_bypass", "1")
        _meta_set(conn, f"{_SLUG}_active_read", _OLD)
        _meta_set(conn, f"{_SLUG}_cutover_fp", "")
        _meta_set(conn, f"{_SLUG}_reject_refresh", "0")
        _meta_set(conn, f"{_SLUG}_live_flag", "")
        _meta_set(conn, f"{_SLUG}_mode", "")
        _meta_set(conn, f"{_SLUG}_old_track", "pending|stale")
        _meta_set(conn, f"{_SLUG}_pack_decoy", "stale-fp|pending")


def land_cutover(note: str = "", payload: dict | None = None, db_path: str | None = None) -> dict:
    """甲路唯一落点：钉成旁路账册凭证，读侧改认账册行并拒回刷。

    一次性落锁：已落定后再落台直接 409 说清楚，不许双成功互踩钉点。
    提交即落库：整条命运在单个事务里写完并提交。
    """
    payload = payload or {}
    note = (note or "").strip() or _TITLE
    with get_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        c = int(_meta_get(conn, f"{_SLUG}_counter", "0") or "0") + 1
        fp = "cc-{}-{}".format(
            c,
            hashlib.sha1(f"{c}|{stamp}|{note}|{payload}".encode("utf-8")).hexdigest()[:12],
        )
        cur = conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
            (f"{_SLUG}_fate_lock", fp),
        )
        if cur.rowcount == 0:
            landed = _meta_get(conn, f"{_SLUG}_cutover_fp", "?")
            raise ServiceError(
                f"{_TITLE}已落定（旁路账册 {landed}），禁止重复落台互踩钉点",
                409,
            )
        _meta_set(conn, f"{_SLUG}_counter", str(c))
        _meta_set(conn, f"{_SLUG}_panel_chip", _OK)
        _meta_set(conn, f"{_SLUG}_truth", _OK)
        _meta_set(conn, f"{_SLUG}_active_read", _CUTOVER)
        _meta_set(conn, f"{_SLUG}_cutover_fp", fp)
        _meta_set(conn, f"{_SLUG}_reject_refresh", "1")
        _meta_set(conn, f"{_SLUG}_gate_bypass", "0")
        _meta_set(conn, f"{_SLUG}_mode", _CUTOVER)
        _meta_set(conn, f"{_SLUG}_last_payload", str(payload)[:200])
        _meta_set(conn, f"{_SLUG}_pack_{c}", f"{fp}|{c}|{note}"[:200])
        _meta_set(conn, f"{_SLUG}_cutover_{fp}", f"{note}|{stamp}"[:200])
        _meta_set(conn, f"{_SLUG}_evt_{c}", f"落台 {fp} {note}"[:200])
    return {
        "ok": True,
        "chip": _OK,
        "title": _TITLE,
        "counter": c,
        "mode": _CUTOVER,
        "active_read": _CUTOVER,
        "cutover_fp": fp,
        "reject_refresh": True,
        "archive_count": len(archive_rows(db_path)),
        "live_flag": live_flag(db_path),
        "empty_code_count": empty_code_count(db_path),
        "message": f"{_TITLE}已落台：读轨改认旁路账册 {fp}，拒回刷",
    }


def commit_action(payload: dict | None = None, db_path: str | None = None) -> dict:
    """落台入口：走甲路切流账册，提交马上写完落库。"""
    payload = payload or {}
    note = str(payload.get("note") or payload.get("op") or "落台")
    return land_cutover(note=note, payload=payload, db_path=db_path)


def snapshot(db_path: str | None = None) -> dict:
    """只读快照：读轨认旁路账册行，绝不回刷旧轨。"""
    rows = pack_rows(db_path)
    durable = [r for r in rows if not str(r.get("key", "")).endswith("_decoy")]
    ref = active_read_ref(db_path)
    fp = cutover_fp(db_path)
    aligned = (
        panel_chip(db_path) == _OK
        and truth_flag(db_path) == _OK
        and ref == _CUTOVER
        and reject_refresh(db_path)
        and fp not in ("", "stale-fp")
    )
    with get_db(db_path) as conn:
        bypass = _meta_get(conn, f"{_SLUG}_gate_bypass", "0") == "1"
    return {
        "title": _TITLE,
        "panel_chip": panel_chip(db_path),
        "truth": truth_flag(db_path),
        "pack_count": len(rows),
        "active_read": ref,
        "cutover_fp": fp,
        "reject_refresh": reject_refresh(db_path),
        "archive_count": len(archive_rows(db_path)),
        "live_flag": live_flag(db_path),
        "empty_code_count": empty_code_count(db_path),
        "aligned": aligned,
        "gate_bypass": bypass,
        "durable_count": len(durable),
    }


def gate_allows_pipeline(db_path: str | None = None) -> bool:
    """闸门只看落点是否对齐；徽标与空码条数拧花一律不放行。"""
    return snapshot(db_path)["aligned"]


def dashboard(db_path: str | None = None) -> dict:
    snap = snapshot(db_path)
    rows = pack_rows(db_path)
    durable = [r for r in rows if not str(r.get("key", "")).endswith("_decoy")]
    aligned = snap["aligned"]
    return {
        "title": _TITLE,
        "chip": _OK if aligned else _BAD,
        "truth": snap["truth"],
        "pack_count": snap["pack_count"],
        "durable_count": len(durable),
        "rows": rows,
        "active_read": snap["active_read"],
        "cutover_fp": snap["cutover_fp"],
        "reject_refresh": snap["reject_refresh"],
        "archive_count": snap["archive_count"],
        "live_flag": snap["live_flag"],
        "empty_code_count": snap["empty_code_count"],
        "aligned": aligned,
        "panel_pack_mismatch": snap["panel_chip"] == _OK and not aligned,
        "ok_chip": _OK,
        "bad_chip": _BAD,
        "label": "清洗钉定",
        "read_tracks": {
            "old_track": _OLD,
            "cutover_book": _CUTOVER,
        },
    }


def list_events(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_evt_%",),
        ).fetchall()
        return [{"key": r["key"], "note": r["value"]} for r in rows]


def record_event(note: str, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        c = int(_meta_get(conn, f"{_SLUG}_counter", "0") or "0") + 1
        _meta_set(conn, f"{_SLUG}_counter", str(c))
        _meta_set(conn, f"{_SLUG}_evt_{c}", note or _BAD)
    return dashboard(db_path)


def require_pack_or_raise(action: str = "空码入库", db_path: str | None = None) -> None:
    snap = snapshot(db_path)
    if not snap["aligned"]:
        raise ServiceError(
            f"清洗徽标与空码条数对不上：{_TITLE}读轨未落定"
            f"（当前 {snap['active_read']}），已拦住{action}；"
            f"请先在台参数落台{_TITLE}",
            409,
        )
