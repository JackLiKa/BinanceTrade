from __future__ import annotations

from gridtrade.api.store import Store


def test_fail_interrupted_only_touches_active_runs(tmp_path):
    store = Store(tmp_path / "test.db")
    queued = store.create_run("replay", "TESTUSDT", {})
    running = store.create_run("replay", "TESTUSDT", {})
    store.update_run(running, status="running")
    finished = store.create_run("replay", "TESTUSDT", {})
    store.update_run(finished, status="succeeded")

    assert store.fail_interrupted("服务重启导致任务中断") == 2

    assert store.get_run(queued)["status"] == "failed"
    row = store.get_run(running)
    assert row["status"] == "failed"
    assert row["message"] == "服务重启导致任务中断"
    assert row["finished_at"] is not None
    assert store.get_run(finished)["status"] == "succeeded"
