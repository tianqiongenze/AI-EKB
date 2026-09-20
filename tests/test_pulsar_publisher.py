from __future__ import annotations

import importlib
from typing import Any

from enterprise_ekb.event_bus import PulsarPublisher


class _FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, dict[str, str]]] = []
        self.flushed = False

    def send(self, payload: bytes, properties: dict[str, str]) -> None:
        self.sent.append((payload, properties))

    def flush(self) -> None:
        self.flushed = True


class _FakeClient:
    def __init__(self) -> None:
        self.producers: dict[str, _FakeProducer] = {}
        self.closed = False

    def create_producer(self, topic: str, **_: Any) -> _FakeProducer:
        producer = _FakeProducer()
        self.producers[topic] = producer
        return producer

    def close(self) -> None:
        self.closed = True


class _FakePulsarModule:
    class CompressionType:
        LZ4 = 2
        NONE = 0
    def __init__(self) -> None:
        self.client = _FakeClient()

    @staticmethod
    def AuthenticationToken(token: str) -> str:
        return token

    def Client(self, *_: Any, **__: Any) -> _FakeClient:  # noqa: N802
        return self.client


def test_pulsar_publisher_uses_batching_client(monkeypatch) -> None:
    fake_module = _FakePulsarModule()
    real_import_module = importlib.import_module

    def fake_import(name: str, package: str | None = None):
        if name == "pulsar":
            return fake_module
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    publisher = PulsarPublisher(service_url="pulsar://unit-test:6650")
    publisher.publish("persistent://group/control/skill-promoted", {"skill": "planner:1.0.0"})
    publisher.publish("persistent://group/control/skill-promoted", {"skill": "qa-agent:2.0.0"})

    producer = fake_module.client.producers["persistent://group/control/skill-promoted"]
    assert len(producer.sent) == 2
    assert producer.sent[0][1]["event_type"] == "skill-promoted"

    publisher.close()
    assert producer.flushed is True
    assert fake_module.client.closed is True
