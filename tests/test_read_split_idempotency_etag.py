from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.a2a_runtime import A2ADispatcher
from enterprise_ekb.app import create_app
from enterprise_ekb.storage import ReplicaRoutingStore, SQLiteControlPlaneStore


def test_replica_routing_store_splits_reads_and_writes() -> None:
    class Recorder:
        def __init__(self, tag: str) -> None:
            self.tag = tag
            self.calls: list[str] = []

        def list_skills(self):
            self.calls.append("list_skills")

        def enqueue_outbox(self, **kwargs):
            self.calls.append("enqueue_outbox")

    primary, replica = Recorder("primary"), Recorder("replica")
    routed = ReplicaRoutingStore(primary=primary, replica=replica)
    routed.list_skills()
    routed.enqueue_outbox(event_type="x", payload={})
    assert replica.calls == ["list_skills"]
    assert primary.calls == ["enqueue_outbox"]


def test_replica_routing_integration_same_file_sqlite(tmp_path: Path) -> None:
    db = str(tmp_path / "shared.db")
    primary = SQLiteControlPlaneStore(db_path=db)
    replica = SQLiteControlPlaneStore(db_path=db)
    routed = ReplicaRoutingStore(primary=primary, replica=replica)
    routed.create_skill_from_manifest = None  # guard: only real methods used below
    routed.enqueue_outbox(event_type="skill.registered", payload={"k": 1})
    stats_via_replica = routed.outbox_stats()
    assert stats_via_replica["pending"] == 1, "write went to primary, read routed to replica (same file)"


def test_a2a_dispatcher_dedups_redelivery() -> None:
    dispatcher = A2ADispatcher(dedup_ttl_seconds=60)
    seen: list[dict] = []
    dispatcher.register("probe", seen.append)
    message = {"message_id": "m-1", "intent": "probe", "payload": {}}
    assert dispatcher.dispatch(message) is True
    assert dispatcher.dispatch(message) is False, "redelivered message must be a no-op"
    assert dispatcher.dispatch({"message_id": "m-2", "intent": "probe", "payload": {}}) is True
    assert len(seen) == 2
    assert dispatcher.duplicates == 1


def test_etag_304_on_readyz_and_metrics(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "etag.db")))
    for path in ("/readyz", "/metrics"):
        first = client.get(path)
        etag = first.headers.get("etag")
        assert etag, f"{path} must expose ETag"
        again = client.get(path, headers={"If-None-Match": etag})
        assert again.status_code == 304, f"{path} must answer 304 on matching If-None-Match"
