"""编码清洗假绿（clinic-bug-10）：甲路 cutover_book 落台验收。

先写败测再改码：
- 落台前：徽标不得假绿、读轨停旧轨、空码入库必须被拦。
- 落台后：旁路账册凭证钉定、拒回刷、闸门才放行。
- 争用：两侧同时落台只能一边成功，另一边要说清楚。
"""

import threading

import pytest

from app.services import code_clean, code_clean_cutover, sites, visits
from app.services import settings as settings_svc
from app.services.errors import ServiceError


def _open_batch(db_path):
    return next(b for b in visits.list_batches(db_path) if b["status"] == "采集中")


def test_seeded_skew_is_honest_bad_and_gate_closed(db_path):
    snap = code_clean.snapshot(db_path)
    assert snap["aligned"] is False
    assert snap["active_read"] == "old_track"
    assert code_clean.gate_allows_pipeline(db_path) is False
    dash = code_clean.dashboard(db_path)
    assert dash["chip"] == "空码仍入"
    assert dash["panel_pack_mismatch"] is True


def test_empty_code_count_is_live(db_path):
    dash = code_clean.dashboard(db_path)
    assert "empty_code_count" in dash
    assert dash["empty_code_count"] >= 1


def test_ingest_blocked_until_fate_landed(db_path):
    batch = _open_batch(db_path)
    with pytest.raises(ServiceError) as exc:
        visits.ingest_ok_rows(batch["id"], db_path=db_path)
    assert exc.value.status_code == 409
    assert "编码清洗" in exc.value.message
    code_clean.commit_action({"op": "落台"}, db_path=db_path)
    out = visits.ingest_ok_rows(batch["id"], db_path=db_path)
    assert out["ingested"] >= 0


def test_commit_lands_cutover_fate(db_path):
    res = code_clean.commit_action({"ref": 1}, db_path=db_path)
    assert res["active_read"] == "cutover_book"
    assert res["reject_refresh"] is True
    assert res["cutover_fp"] not in ("", "stale-fp")
    snap = code_clean.snapshot(db_path)
    assert snap["aligned"] is True
    assert snap["truth"] == "清洗已亮"
    assert code_clean.gate_allows_pipeline(db_path) is True
    dash = code_clean.dashboard(db_path)
    assert dash["chip"] == "清洗已亮"
    assert dash["panel_pack_mismatch"] is False
    assert dash["durable_count"] >= 1


def test_read_side_does_not_reskew_after_landing(db_path):
    code_clean.commit_action({"ref": 1}, db_path=db_path)
    for _ in range(3):
        snap = code_clean.snapshot(db_path)
        assert snap["aligned"] is True
        assert snap["active_read"] == "cutover_book"
        assert snap["reject_refresh"] is True


def test_double_commit_rejected_with_clear_message(db_path):
    code_clean.commit_action({"ref": 1}, db_path=db_path)
    with pytest.raises(ServiceError) as exc:
        code_clean.commit_action({"ref": 2}, db_path=db_path)
    assert exc.value.status_code == 409
    assert "已落定" in exc.value.message


def test_concurrent_landing_single_winner(db_path):
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(i):
        barrier.wait(timeout=10)
        try:
            code_clean.commit_action({"worker": i}, db_path=db_path)
            outcomes.append("ok")
        except ServiceError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["conflict", "ok"]
    snap = code_clean.snapshot(db_path)
    assert snap["aligned"] is True


def test_cutover_append_lands_same_fate_and_locks(db_path):
    res = code_clean_cutover.append_cutover(7, "编码清洗", db_path=db_path)
    assert res["active_read"] == "cutover_book"
    assert res["reject_refresh"] is True
    assert res["cutover_fp"] not in ("", "stale-fp")
    with pytest.raises(ServiceError) as exc:
        code_clean.commit_action({"ref": 9}, db_path=db_path)
    assert exc.value.status_code == 409


def test_settings_and_quota_do_not_paint_fake_green(db_path):
    settings_svc.update_setting("qc_auto_scan", "1", db_path=db_path)
    site = next(s for s in sites.list_sites(db_path) if s["status"] == "启用")
    sites.update_quota(site["id"], 55, db_path=db_path)
    snap = code_clean.snapshot(db_path)
    assert snap["aligned"] is False
    assert code_clean.dashboard(db_path)["chip"] == "空码仍入"
