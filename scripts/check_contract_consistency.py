from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
APP_FILE = ROOT / "src" / "enterprise_ekb" / "app.py"
OPENAPI_FILE = ROOT / "contracts" / "openapi" / "control-plane.openapi.yaml"
PULSAR_FILE = ROOT / "contracts" / "pulsar-topics.yaml"
A2A_PROTOCOL_FILE = ROOT / "contracts" / "a2a-protocol.yaml"
CONNECTORS_FILE = ROOT / "src" / "enterprise_ekb" / "connectors.py"
ICEBERG_TABLES_FILE = ROOT / "contracts" / "iceberg-tables.yaml"
FLINK_PIPELINES_FILE = ROOT / "contracts" / "flink-pipelines.yaml"
FLINK_BASE_JOBMANAGER_DEPLOYMENT = ROOT / "infra" / "k8s" / "base" / "flink-deployment-session-cluster.yaml"
FLINK_BASE_JOBMANAGER_SERVICE = ROOT / "infra" / "k8s" / "base" / "service-flink-session-cluster.yaml"


@dataclass(frozen=True)
class RouteContract:
    method: str
    path: str


def _load_yaml(path: Path) -> dict[str, Any]:
    yaml = importlib.import_module("yaml")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _extract_app_routes_from_ast(path: Path) -> set[RouteContract]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    routes: set[RouteContract] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if isinstance(func, ast.Attribute):
                # FastAPI/Starlette style: @api.get("/path")
                if not isinstance(func.value, ast.Name) or func.value.id != "api":
                    continue
                method = func.attr.lower()
            elif isinstance(func, ast.Name):
                # Litestar style: @get("/path", sync_to_thread=True)
                method = func.id.lower()
            else:
                continue
            if method not in {"get", "post", "put", "delete", "patch", "options", "head"}:
                continue
            if not decorator.args:
                continue
            first_arg = decorator.args[0]
            if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue
            # Normalize Litestar typed path params ({p:str}) to OpenAPI form ({p})
            route_path = re.sub(r"\{(\w+):[^}]+\}", r"{\1}", first_arg.value)
            routes.add(RouteContract(method=method, path=route_path))

    return routes


def _extract_openapi_routes(path: Path) -> set[RouteContract]:
    payload = _load_yaml(path)
    paths_obj = payload.get("paths", {})
    if not isinstance(paths_obj, dict):
        raise ValueError("OpenAPI 'paths' must be a mapping")

    routes: set[RouteContract] = set()
    for route_path, operations in paths_obj.items():
        if not isinstance(route_path, str) or not isinstance(operations, dict):
            continue
        for method in operations.keys():
            if not isinstance(method, str):
                continue
            method_lower = method.lower()
            if method_lower not in {"get", "post", "put", "delete", "patch", "options", "head"}:
                continue
            routes.add(RouteContract(method=method_lower, path=route_path))
    return routes


def _extract_outbox_event_types_from_ast(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    event_types: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "enqueue_outbox":
            continue

        for keyword in node.keywords:
            if keyword.arg != "event_type":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                event_types.add(value.value)

    return event_types


def _has_dynamic_connector_event_pattern(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return 'event_type=f"connector.{envelope.connector_system.value}.ingested"' in text


def _extract_pulsar_event_types(path: Path) -> set[str]:
    payload = _load_yaml(path)
    topics = payload.get("topics", [])
    if not isinstance(topics, list):
        raise ValueError("Pulsar contract 'topics' must be a list")

    event_types: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        event_type = topic.get("event_type")
        if isinstance(event_type, str):
            event_types.add(event_type)

    return event_types


def _extract_openapi_schema_fields(path: Path, schema_name: str) -> set[str]:
    payload = _load_yaml(path)
    components = payload.get("components", {})
    if not isinstance(components, dict):
        raise ValueError("OpenAPI components missing or invalid")

    schemas = components.get("schemas", {})
    if not isinstance(schemas, dict):
        raise ValueError("OpenAPI components.schemas missing or invalid")

    schema_obj = schemas.get(schema_name, {})
    if not isinstance(schema_obj, dict):
        raise ValueError(f"OpenAPI schema missing or invalid: {schema_name}")

    properties = schema_obj.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError(f"OpenAPI schema properties missing or invalid: {schema_name}")

    return {k for k in properties.keys() if isinstance(k, str)}


def _extract_a2a_protocol_fields(path: Path) -> set[str]:
    payload = _load_yaml(path)
    envelope = payload.get("envelope", {})
    if not isinstance(envelope, dict):
        raise ValueError("A2A protocol envelope missing or invalid")

    properties = envelope.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("A2A protocol envelope.properties missing or invalid")

    return {k for k in properties.keys() if isinstance(k, str)}


def _format_set(values: set[str]) -> str:
    return json.dumps(sorted(values), ensure_ascii=False)


def _extract_iceberg_table_names(path: Path) -> set[str]:
    payload = _load_yaml(path)
    tables = payload.get("tables", [])
    if not isinstance(tables, list):
        raise ValueError("iceberg-tables contract 'tables' must be a list")
    names: set[str] = set()
    for table in tables:
        if isinstance(table, dict) and isinstance(table.get("name"), str):
            names.add(str(table["name"]))
    return names


def _extract_flink_sink_tables(path: Path) -> set[str]:
    payload = _load_yaml(path)
    pipelines = payload.get("pipelines", [])
    if not isinstance(pipelines, list):
        raise ValueError("flink-pipelines contract 'pipelines' must be a list")
    sink_tables: set[str] = set()
    for pipeline in pipelines:
        if isinstance(pipeline, dict) and isinstance(pipeline.get("sink_table"), str):
            sink_tables.add(str(pipeline["sink_table"]))
    return sink_tables


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run() -> int:
    failures: list[str] = []

    app_routes = _extract_app_routes_from_ast(APP_FILE)
    openapi_routes = _extract_openapi_routes(OPENAPI_FILE)
    app_route_keys = {f"{r.method.upper()} {r.path}" for r in app_routes}
    openapi_route_keys = {f"{r.method.upper()} {r.path}" for r in openapi_routes}

    app_not_in_openapi = app_route_keys - openapi_route_keys
    openapi_not_in_app = openapi_route_keys - app_route_keys
    if app_not_in_openapi or openapi_not_in_app:
        failures.append(
            "Route contract mismatch:\n"
            f"- Implemented but not in OpenAPI: {_format_set(app_not_in_openapi)}\n"
            f"- OpenAPI but not implemented: {_format_set(openapi_not_in_app)}"
        )

    app_event_types = _extract_outbox_event_types_from_ast(APP_FILE)
    pulsar_event_types = _extract_pulsar_event_types(PULSAR_FILE)
    app_event_not_in_contract = app_event_types - pulsar_event_types
    if app_event_not_in_contract:
        failures.append(
            "Outbox event contract mismatch:\n"
            f"- event_type used in app.py but missing in pulsar-topics.yaml: {_format_set(app_event_not_in_contract)}"
        )

    pulsar_payload = _load_yaml(PULSAR_FILE)
    tenancy = pulsar_payload.get("tenancy", {}) if isinstance(pulsar_payload, dict) else {}
    namespaces = tenancy.get("namespaces", []) if isinstance(tenancy, dict) else []
    namespace_set = {ns for ns in namespaces if isinstance(ns, str)}
    required_namespaces = {"control", "audit", "observability", "a2a", "a2a-dlq"}
    missing_namespaces = required_namespaces - namespace_set
    if missing_namespaces:
        failures.append(
            "Pulsar tenancy namespace mismatch:\n"
            f"- missing required namespaces in pulsar-topics.yaml: {_format_set(missing_namespaces)}"
        )

    required_domain_events = {
        "domain.capability.upserted",
        "domain.capabilities.bootstrapped",
    }
    missing_domain_events = required_domain_events - app_event_types
    if missing_domain_events:
        failures.append(
            "Domain capability events missing in app.py outbox usage:\n"
            f"- missing: {_format_set(missing_domain_events)}"
        )

    required_connector_events = {
        "connector.erp.ingested",
        "connector.mes.ingested",
        "connector.scada.ingested",
        "connector.ticketing.ingested",
        "connector.profile.upserted",
        "connector.checkpoint.updated",
        "connector.pull.executed",
    }
    missing_connector_events = required_connector_events - app_event_types
    has_dynamic_connector_pattern = _has_dynamic_connector_event_pattern(CONNECTORS_FILE)
    if missing_connector_events and not has_dynamic_connector_pattern:
        failures.append(
            "Connector events missing in app.py outbox usage:\n"
            f"- missing: {_format_set(missing_connector_events)}"
        )

    openapi_a2a_fields = _extract_openapi_schema_fields(OPENAPI_FILE, "A2AEnvelope")
    protocol_a2a_fields = _extract_a2a_protocol_fields(A2A_PROTOCOL_FILE)
    openapi_not_in_protocol = openapi_a2a_fields - protocol_a2a_fields
    protocol_not_in_openapi = protocol_a2a_fields - openapi_a2a_fields
    if openapi_not_in_protocol or protocol_not_in_openapi:
        failures.append(
            "A2A envelope contract mismatch:\n"
            f"- OpenAPI only fields: {_format_set(openapi_not_in_protocol)}\n"
            f"- A2A protocol only fields: {_format_set(protocol_not_in_openapi)}"
        )

    iceberg_tables = _extract_iceberg_table_names(ICEBERG_TABLES_FILE)
    flink_sink_tables = _extract_flink_sink_tables(FLINK_PIPELINES_FILE)
    unknown_flink_sinks = flink_sink_tables - iceberg_tables
    if unknown_flink_sinks:
        failures.append(
            "Flink/Iceberg contract mismatch:\n"
            f"- sink_table in flink-pipelines.yaml missing from iceberg-tables.yaml: {_format_set(unknown_flink_sinks)}"
        )

    deployment_text = _read_text(FLINK_BASE_JOBMANAGER_DEPLOYMENT)
    service_text = _read_text(FLINK_BASE_JOBMANAGER_SERVICE)
    if "jobmanager.rpc.address: flink-jobmanager" not in deployment_text:
        failures.append(
            "Flink base deployment mismatch:\n"
            "- expected jobmanager.rpc.address: flink-jobmanager in flink-deployment-session-cluster.yaml"
        )
    if "name: flink-jobmanager" not in service_text:
        failures.append(
            "Flink base service mismatch:\n"
            "- expected service name flink-jobmanager in service-flink-session-cluster.yaml"
        )

    if failures:
        print("[contract-consistency] FAILED")
        for failure in failures:
            print("\n" + failure)
        return 1

    print("[contract-consistency] PASS")
    print(f"- routes checked: {len(app_route_keys)}")
    print(f"- outbox event types checked: {len(app_event_types)}")
    print(f"- a2a fields checked: {len(openapi_a2a_fields)}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
