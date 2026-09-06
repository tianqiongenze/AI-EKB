from pathlib import Path

from enterprise_ekb.event_bus import InMemoryPublisher, OutboxRelay
from enterprise_ekb.schemas import SkillManifest, SkillRiskLevel, SkillStage
from enterprise_ekb.storage import SQLiteControlPlaneStore


def test_store_persists_skill_and_audit_and_outbox(tmp_path: Path) -> None:
    db_path = tmp_path / "control_plane.db"
    store = SQLiteControlPlaneStore(db_path=str(db_path))

    manifest = SkillManifest(
        skill_name="planner",
        version="1.0.0",
        owner="platform",
        risk_level=SkillRiskLevel.low,
        allowed_tools=["plan.create"],
        allowed_domains=["planning"],
        residency_scope=["cn-north-1"],
        changelog="init",
    )
    store.create_skill(manifest=manifest, stage=SkillStage.draft)
    skills = store.list_skills()
    assert len(skills) == 1
    assert skills[0].manifest.skill_name == "planner"

    store.append_audit(
        tenant_id="group",
        region_id="cn-north-1",
        plant_id="plant-bj",
        user_or_agent_id="user-01",
        skill_name="planner",
        skill_version="1.0.0",
        tool_name="plan.create",
        decision_reason="ok",
        accepted=True,
        payload={"foo": "bar"},
    )
    audits = store.recent_audits(limit=10)
    assert len(audits) == 1
    assert audits[0]["accepted"] is True

    store.enqueue_outbox(
        "skill.registered",
        {
            "skill_name": "planner",
            "version": "1.0.0",
            "stage": "draft",
            "owner": "platform",
        },
    )
    pending = store.next_pending_outbox(limit=10)
    assert len(pending) == 1


def test_outbox_relay_publishes_pending_events(tmp_path: Path) -> None:
    db_path = tmp_path / "control_plane.db"
    store = SQLiteControlPlaneStore(db_path=str(db_path))
    store.enqueue_outbox(
        "skill.promoted",
        {
            "skill_name": "planner",
            "version": "1.0.0",
            "stage": "review",
        },
    )
    store.enqueue_outbox(
        "harness.evaluated",
        {
            "tenant_id": "group",
            "skill": "planner:1.0.0",
            "accepted": True,
            "reasons": [],
        },
    )

    publisher = InMemoryPublisher()
    relay = OutboxRelay(store=store, publisher=publisher)
    result = relay.run_once(batch_size=10)

    assert result["published"] == 2
    assert len(publisher.published) == 2
    stats = store.outbox_stats()
    assert stats["pending"] == 0
    assert stats["published"] == 2


def test_outbox_claims_pending_before_publish(tmp_path: Path) -> None:
    db_path = tmp_path / "control_plane.db"
    store = SQLiteControlPlaneStore(db_path=str(db_path))
    store.enqueue_outbox(
        "skill.promoted",
        {
            "skill_name": "planner",
            "version": "1.0.1",
            "stage": "review",
        },
    )

    claimed = store.claim_pending_outbox(limit=10)
    assert len(claimed) == 1
    stats = store.outbox_stats()
    assert stats["processing"] == 1

    event_id = int(claimed[0]["id"])
    store.mark_outbox_published(event_id=event_id)
    stats_after = store.outbox_stats()
    assert stats_after["processing"] == 0
    assert stats_after["published"] == 1


def test_outbox_failed_requeues_with_backoff(tmp_path: Path) -> None:
    db_path = tmp_path / "control_plane.db"
    store = SQLiteControlPlaneStore(db_path=str(db_path))
    event_id = store.enqueue_outbox(
        "skill.promoted",
        {
            "skill_name": "planner",
            "version": "1.0.2",
            "stage": "staging",
        },
    )

    claimed = store.claim_pending_outbox(limit=10)
    assert len(claimed) == 1
    store.mark_outbox_failed(event_id=event_id, error="transient_error")

    stats = store.outbox_stats()
    assert stats["pending"] == 1
    assert stats["processing"] == 0
