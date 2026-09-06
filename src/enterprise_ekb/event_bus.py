from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from enterprise_ekb.middleware_clients import HighPerformancePulsarClient, PulsarConfig
from enterprise_ekb.storage import SQLiteControlPlaneStore


class EventPublisher(Protocol):
    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        ...

    def publish_batch(self, topic: str, payloads: list[dict[str, Any]]) -> None:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class PublishedEvent:
    topic: str
    payload: dict[str, Any]


class InMemoryPublisher:
    def __init__(self) -> None:
        self.published: list[PublishedEvent] = []

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.published.append(PublishedEvent(topic=topic, payload=payload))

    def publish_batch(self, topic: str, payloads: list[dict[str, Any]]) -> None:
        for payload in payloads:
            self.publish(topic=topic, payload=payload)

    def close(self) -> None:
        return None


class PulsarPublisher:
    def __init__(
        self,
        service_url: str,
        token: str = "",
        tls_enabled: bool = False,
        ca_cert_path: str = "",
    ) -> None:
        self._client = HighPerformancePulsarClient(
            PulsarConfig(
                service_url=service_url,
                token=token,
                tls_enabled=tls_enabled,
                ca_cert_path=ca_cert_path,
            )
        )

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self._client.publish_batch(topic=topic, payloads=[payload])

    def publish_batch(self, topic: str, payloads: list[dict[str, Any]]) -> None:
        self._client.publish_batch(topic=topic, payloads=payloads)

    def close(self) -> None:
        self._client.close()


class OutboxRelay:
    def __init__(self, store: SQLiteControlPlaneStore, publisher: EventPublisher) -> None:
        self.store = store
        self.publisher = publisher

    def run_once(self, batch_size: int = 100) -> dict[str, int]:
        events = self.store.claim_pending_outbox(limit=batch_size)
        published_count = 0
        failed_count = 0
        scanned_count = len(events)
        grouped: dict[str, list[dict[str, Any]]] = {}
        grouped_ids: dict[str, list[int]] = {}

        for event in events:
            event_type = str(event["event_type"])
            payload = dict(event["payload"])
            topic = self._resolve_topic(event_type=event_type, payload=payload)
            grouped.setdefault(topic, []).append(self._normalized_payload(event_type=event_type, payload=payload))
            grouped_ids.setdefault(topic, []).append(int(event["id"]))

        for topic, payloads in grouped.items():
            ids = grouped_ids[topic]
            try:
                self.publisher.publish_batch(topic=topic, payloads=payloads)
                for event_id in ids:
                    self.store.mark_outbox_published(event_id=event_id)
                    published_count += 1
            except Exception as exc:
                for event_id in ids:
                    self.store.mark_outbox_failed(event_id=event_id, error=str(exc))
                    failed_count += 1
        return {
            "scanned": scanned_count,
            "published": published_count,
            "failed": failed_count,
        }

    @staticmethod
    def _event_topic(event_type: str) -> str:
        topic_map = {
            "skill.registered": "persistent://group/control/skill-registered",
            "skill.promoted": "persistent://group/control/skill-promoted",
            "mcp.invoked": "persistent://group/audit/mcp-invoke",
            "harness.evaluated": "persistent://group/audit/harness-evaluated",
            "capacity.estimated": "persistent://group/observability/capacity-estimated",
            "a2a.message": "persistent://group/a2a/default",
            "a2a.subagent.retry": "persistent://group/a2a/retry",
            "a2a.subagent.dlq": "persistent://group/a2a/dlq",
            "a2a.supervision.scan.executed": "persistent://group/audit/a2a-supervision-scan-executed",
            "a2a.supervision.alerted": "persistent://group/audit/a2a-supervision-alerted",
            "domain.capability.upserted": "persistent://group/control/domain-capability-upserted",
            "domain.capabilities.bootstrapped": "persistent://group/control/domain-capabilities-bootstrapped",
            "connector.erp.ingested": "persistent://group/connectors/erp-ingested",
            "connector.mes.ingested": "persistent://group/connectors/mes-ingested",
            "connector.scada.ingested": "persistent://group/connectors/scada-ingested",
            "connector.ticketing.ingested": "persistent://group/connectors/ticketing-ingested",
            "connector.profile.upserted": "persistent://group/connectors/profile-upserted",
            "connector.checkpoint.updated": "persistent://group/connectors/checkpoint-updated",
            "connector.pull.executed": "persistent://group/connectors/pull-executed",
            "datalake.table.registered": "persistent://group/control/datalake-table-registered",
            "flink.pipeline.registered": "persistent://group/control/flink-pipeline-registered",
            "flywheel.event.recorded": "persistent://group/observability/flywheel-event-recorded",
            "datapipeline.supervision.scan.executed": "persistent://group/audit/datapipeline-supervision-scan-executed",
            "datapipeline.supervision.alerted": "persistent://group/audit/datapipeline-supervision-alerted",
        }
        return topic_map.get(event_type, "persistent://group/control/misc")

    @staticmethod
    def _resolve_topic(event_type: str, payload: dict[str, Any]) -> str:
        if event_type == "a2a.message":
            explicit_topic = payload.get("topic")
            if isinstance(explicit_topic, str) and explicit_topic:
                return explicit_topic
        return OutboxRelay._event_topic(event_type=event_type)

    @staticmethod
    def _normalized_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        known_event_types = {
            "skill.registered",
            "skill.promoted",
            "mcp.invoked",
            "harness.evaluated",
            "capacity.estimated",
            "a2a.message",
            "a2a.subagent.retry",
            "a2a.subagent.dlq",
            "a2a.supervision.scan.executed",
            "a2a.supervision.alerted",
            "domain.capability.upserted",
            "domain.capabilities.bootstrapped",
            "connector.erp.ingested",
            "connector.mes.ingested",
            "connector.scada.ingested",
            "connector.ticketing.ingested",
            "connector.profile.upserted",
            "connector.checkpoint.updated",
            "connector.pull.executed",
            "datalake.table.registered",
            "flink.pipeline.registered",
            "flywheel.event.recorded",
            "datapipeline.supervision.scan.executed",
            "datapipeline.supervision.alerted",
        }
        if event_type in known_event_types:
            return payload
        return {
            "event_type": event_type,
            "payload": payload,
        }
