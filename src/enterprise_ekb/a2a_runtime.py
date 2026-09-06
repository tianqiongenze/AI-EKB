from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from enterprise_ekb.middleware_clients import HighPerformancePulsarClient, PulsarConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class A2AConsumerConfig:
    service_url: str
    token: str
    tls_enabled: bool
    ca_cert_path: str
    topic: str
    subscription: str


class A2ADispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {}

    def register(self, intent: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._handlers[intent] = handler

    def dispatch(self, payload: dict[str, Any]) -> None:
        intent = str(payload.get("intent", ""))
        handler = self._handlers.get(intent)
        if handler is None:
            raise ValueError(f"no handler registered for intent: {intent}")
        handler(payload)


class A2AConsumer:
    def __init__(self, config: A2AConsumerConfig, dispatcher: A2ADispatcher) -> None:
        pulsar_module = __import__("pulsar")
        auth = pulsar_module.AuthenticationToken(config.token) if config.token else None
        self._client = pulsar_module.Client(
            config.service_url,
            authentication=auth,
            tls_validate_hostname=config.tls_enabled,
            tls_trust_certs_file_path=config.ca_cert_path if config.ca_cert_path else None,
        )
        self._consumer = self._client.subscribe(
            config.topic,
            subscription_name=config.subscription,
            consumer_type=pulsar_module.ConsumerType.Shared,
        )
        self._dispatcher = dispatcher

    def run_once(self) -> bool:
        message = self._consumer.receive(timeout_millis=1000)
        if message is None:
            return False
        try:
            payload = json.loads(message.data().decode("utf-8"))
            self._dispatcher.dispatch(payload)
            self._consumer.acknowledge(message)
            return True
        except Exception:
            self._consumer.negative_acknowledge(message)
            raise

    def close(self) -> None:
        self._consumer.close()
        self._client.close()


def build_a2a_consumer(config: A2AConsumerConfig) -> A2AConsumer:
    dispatcher = A2ADispatcher()

    def default_handler(payload: dict[str, Any]) -> None:
        _ = payload

    def route_task_handler(payload: dict[str, Any]) -> None:
        target_agent = payload.get("target_agent")
        task_payload = payload.get("payload", {})
        logger.info("a2a.route_task", extra={"target_agent": target_agent, "payload": task_payload})

    def evaluate_skill_handler(payload: dict[str, Any]) -> None:
        tenant_id = payload.get("tenant_id")
        intent = payload.get("intent")
        logger.info("a2a.evaluate_skill", extra={"tenant_id": tenant_id, "intent": intent})

    def delegate_sub_task_handler(payload: dict[str, Any]) -> None:
        target_agent = payload.get("target_agent")
        task_payload = payload.get("payload", {})
        supervisor_id = payload.get("metadata", {}).get("supervisor_id")
        task_id = task_payload.get("task_id")
        logger.info(
            "a2a.delegate_sub_task",
            extra={
                "target_agent": target_agent,
                "supervisor_id": supervisor_id,
                "task_id": task_id,
            },
        )

    def sub_task_result_handler(payload: dict[str, Any]) -> None:
        task_payload = payload.get("payload", {})
        logger.info(
            "a2a.sub_task_result",
            extra={
                "task_id": task_payload.get("task_id"),
                "status": task_payload.get("status"),
                "worker_id": task_payload.get("worker_id"),
            },
        )

    dispatcher.register("route_task", default_handler)
    dispatcher.register("route_task.v2", route_task_handler)
    dispatcher.register("evaluate_skill", evaluate_skill_handler)
    dispatcher.register("delegate_sub_task", delegate_sub_task_handler)
    dispatcher.register("sub_task_result", sub_task_result_handler)

    return A2AConsumer(config=config, dispatcher=dispatcher)
