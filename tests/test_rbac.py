"""P0-④ RBAC tests: unit (RBACService + fake store) and API (guarded by route-mount skip)."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

from enterprise_ekb.rbac import (
    ALL_LAYERS,
    LAYER_APPLICATION,
    LAYER_DATA,
    LAYER_FUNCTION,
    LAYER_SYSTEM,
    ROLE_DEFINITIONS,
    ROLE_PERMISSION_LAYERS,
    PermissionDeniedError,
    RBACService,
    layer_implies,
)

EXPECTED_ROLES = {
    "A1": ("P1", True),
    "A2": ("P2", True),
    "A3": ("P2", True),
    "B1": ("P3", True),
    "B2": ("P3", True),
    "B3": ("P3", True),
    "C1": ("P4", True),
    "C2": ("P4", True),
    "C3": ("P4", True),
    "D1": ("P3", False),
    "D2": ("P2", False),
    "D3": ("P4", False),
}


class FakeRBACStore:
    """In-memory implementation of the control-plane store contract."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}

    def upsert_user(self, user_id: str, role: str, tenant_id: str, department: str) -> None:
        self.users[user_id] = {
            "user_id": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "department": department,
        }

    def get_user_role(self, user_id: str) -> str | None:
        record = self.users.get(user_id)
        return record["role"] if record else None

    def list_users(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self.users.values()]

    def delete_user(self, user_id: str) -> None:
        self.users.pop(user_id, None)


# ---------------------------------------------------------------------------
# Unit: role definitions and layer hierarchy
# ---------------------------------------------------------------------------


def test_role_definitions_cover_all_twelve_roles() -> None:
    assert set(ROLE_DEFINITIONS) == set(EXPECTED_ROLES)
    for code, (layer, human) in EXPECTED_ROLES.items():
        meta = ROLE_DEFINITIONS[code]
        assert meta["code"] == code
        assert meta["name"]
        assert meta["layer"] == layer
        assert meta["description"]
        assert meta["human"] is human
    assert sum(1 for m in ROLE_DEFINITIONS.values() if m["human"]) == 9
    assert sum(1 for m in ROLE_DEFINITIONS.values() if not m["human"]) == 3


def test_layer_implies_hierarchy_inheritance() -> None:
    assert layer_implies(LAYER_SYSTEM) == frozenset({"P1", "P2", "P3", "P4"})
    assert layer_implies(LAYER_APPLICATION) == frozenset({"P2", "P3", "P4"})
    assert layer_implies(LAYER_DATA) == frozenset({"P3", "P4"})
    assert layer_implies(LAYER_FUNCTION) == frozenset({"P4"})
    with pytest.raises(ValueError):
        layer_implies("P5")
    with pytest.raises(ValueError):
        layer_implies("")


def test_role_permission_layers_expand_inheritance() -> None:
    # A1 (P1) inherits every layer down to P4; C3 (P4) holds only P4.
    assert ROLE_PERMISSION_LAYERS["A1"] == {"P1", "P2", "P3", "P4"}
    assert ROLE_PERMISSION_LAYERS["A2"] == {"P2", "P3", "P4"}
    assert ROLE_PERMISSION_LAYERS["A3"] == {"P2", "P3", "P4"}
    assert ROLE_PERMISSION_LAYERS["B1"] == {"P3", "P4"}
    assert ROLE_PERMISSION_LAYERS["B2"] == {"P3", "P4"}
    assert ROLE_PERMISSION_LAYERS["B3"] == {"P3", "P4"}
    assert ROLE_PERMISSION_LAYERS["C1"] == {"P4"}
    assert ROLE_PERMISSION_LAYERS["C2"] == {"P4"}
    assert ROLE_PERMISSION_LAYERS["C3"] == {"P4"}
    # Non-human roles are not mapped to any P-layer by the spec.
    for non_human in ("D1", "D2", "D3"):
        assert ROLE_PERMISSION_LAYERS[non_human] == set()


def test_describe_roles_returns_full_metadata() -> None:
    service = RBACService(store=FakeRBACStore())
    roles = service.describe_roles()
    assert len(roles) == 12
    for meta in roles:
        assert {"code", "name", "layer", "description", "human", "layers"} <= set(meta)
        assert meta["layers"] == sorted(ROLE_PERMISSION_LAYERS[meta["code"]])
    # Mutating the returned copies must not corrupt module state.
    roles[0]["name"] = "tampered"
    assert ROLE_DEFINITIONS[roles[0]["code"]]["name"] != "tampered"


# ---------------------------------------------------------------------------
# Unit: RBACService behaviour
# ---------------------------------------------------------------------------


def test_assign_and_get_role_roundtrip() -> None:
    store = FakeRBACStore()
    service = RBACService(store=store)
    service.assign_role("u-admin", "A1", tenant_id="group", department="IT")
    service.assign_role("u-editor", "B2")
    assert service.get_role("u-admin") == "A1"
    assert service.get_role("u-editor") == "B2"
    assert store.users["u-admin"] == {
        "user_id": "u-admin",
        "role": "A1",
        "tenant_id": "group",
        "department": "IT",
    }
    # Upsert semantics: reassigning replaces the binding.
    service.assign_role("u-editor", "B1")
    assert service.get_role("u-editor") == "B1"
    # Store passthroughs.
    assert service.list_users() == list(store.users.values())
    assert service.delete_user("u-editor") is True
    assert service.get_role("u-editor") == "C2"


def test_unregistered_user_falls_back_to_default_role() -> None:
    service = RBACService(store=FakeRBACStore())
    assert service.get_role("nobody") == "C2"
    custom = RBACService(store=FakeRBACStore(), default_role="C3")
    assert custom.get_role("nobody") == "C3"
    with pytest.raises(ValueError):
        RBACService(store=FakeRBACStore(), default_role="Z9")


def test_store_none_degrades_to_default_role() -> None:
    service = RBACService(store=None)
    assert service.get_role("anyone") == "C2"
    assert service.get_role("") == "C2"
    assert service.list_users() == []
    assert service.delete_user("anyone") is False
    with pytest.raises(RuntimeError):
        service.assign_role("u1", "A1")


def test_assign_role_rejects_invalid_input() -> None:
    service = RBACService(store=FakeRBACStore())
    with pytest.raises(ValueError):
        service.assign_role("u1", "A9")
    with pytest.raises(ValueError):
        service.assign_role("u1", "")
    with pytest.raises(ValueError):
        service.assign_role("", "A1")


def test_require_layers_grants_within_inherited_layers() -> None:
    store = FakeRBACStore()
    service = RBACService(store=store)
    service.assign_role("u-admin", "A1")
    for layer in ("P1", "P2", "P3", "P4"):
        service.require_layers("u-admin", layer)  # A1 holds P1..P4, no raise.
    service.assign_role("u-editor", "B2")
    service.require_layers("u-editor", "P3")
    service.require_layers("u-editor", "P4")
    with pytest.raises(PermissionDeniedError):
        service.require_layers("u-editor", "P2")
    service.assign_role("u-guest", "C3")
    service.require_layers("u-guest", "P4")
    with pytest.raises(PermissionDeniedError):
        service.require_layers("u-guest", "P3")


def test_require_layers_applies_default_role_to_unregistered_user() -> None:
    service = RBACService(store=FakeRBACStore())
    service.require_layers("stranger", "P4")  # default C2 satisfies P4.
    with pytest.raises(PermissionDeniedError):
        service.require_layers("stranger", "P1")


def test_require_layers_rejects_unknown_layer() -> None:
    service = RBACService(store=FakeRBACStore())
    with pytest.raises(ValueError):
        service.require_layers("u1", "P9")


def test_permission_denied_error_attributes() -> None:
    store = FakeRBACStore()
    service = RBACService(store=store)
    service.assign_role("u-guest", "C3")
    with pytest.raises(PermissionDeniedError) as excinfo:
        service.require_layers("u-guest", "P1")
    err = excinfo.value
    assert err.user_id == "u-guest"
    assert err.role == "C3"
    assert err.needed_layer == "P1"
    assert "P1" in str(err)


def test_non_human_roles_have_no_standing_layers() -> None:
    store = FakeRBACStore()
    service = RBACService(store=store)
    service.assign_role("agent-1", "D1")
    assert service.get_role("agent-1") == "D1"
    for layer in ALL_LAYERS:
        with pytest.raises(PermissionDeniedError):
            service.require_layers("agent-1", layer)


# ---------------------------------------------------------------------------
# API tests (active once create_app mounts enterprise_ekb.api.admin)
# ---------------------------------------------------------------------------


def _rbac_routes_mounted(app: Any) -> bool:
    return any("/admin/rbac/roles" in str(getattr(route, "path", route)) for route in app.routes)


@pytest.fixture(scope="module")
def rbac_client() -> Any:
    # Non-production env without auth token: admin auth passes with a warning,
    # matching the behaviour asserted by tests/test_admin_auth_production.py.
    os.environ.pop("EKB_ENV", None)
    os.environ.pop("EKB_AUTH_TOKEN", None)
    with tempfile.TemporaryDirectory() as tmp:
        from enterprise_ekb.app import create_app

        app = create_app(db_path=str(Path(tmp) / "rbac.db"))
        if not _rbac_routes_mounted(app):
            pytest.skip("admin RBAC routes not yet mounted in create_app; re-enable after wiring")
        with TestClient(app=app) as client:
            yield client


def test_api_role_catalog_returns_twelve_roles(rbac_client: Any) -> None:
    resp = rbac_client.get("/admin/rbac/roles")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 12
    assert {role["code"] for role in body} == set(EXPECTED_ROLES)
    admin = next(role for role in body if role["code"] == "A1")
    assert admin["layers"] == ["P1", "P2", "P3", "P4"]


def test_api_assign_list_delete_user_role_binding(rbac_client: Any) -> None:
    user_id = f"rbac-user-{uuid.uuid4().hex[:8]}"
    resp = rbac_client.post("/admin/rbac/users", json={"user_id": user_id, "role": "B1"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": user_id, "role": "B1"}

    listed = rbac_client.get("/admin/rbac/users")
    assert listed.status_code == 200
    assert any(entry.get("user_id") == user_id and entry.get("role") == "B1" for entry in listed.json())

    removed = rbac_client.delete(f"/admin/rbac/users/{user_id}")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    listed_after = rbac_client.get("/admin/rbac/users")
    assert all(entry.get("user_id") != user_id for entry in listed_after.json())


def test_api_assign_invalid_role_returns_400(rbac_client: Any) -> None:
    resp = rbac_client.post("/admin/rbac/users", json={"user_id": "bad-role-user", "role": "Z9"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# RBAC 接线（0.7.1）：用户级凭据走角色层判定
# ---------------------------------------------------------------------------
def _bind(client, user_id, role, token):
    return client.post(
        "/admin/rbac/users",
        json={"user_id": user_id, "role": role},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_rbac_enforcement_c2_user_cannot_ingest(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from enterprise_ekb.app import create_app

    monkeypatch.setenv("EKB_AUTH_TOKEN", "t1")
    app = create_app(db_path=str(tmp_path / "rbac_wire.db"))
    c = TestClient(app)
    import base64

    body = {"source_name": "x.md", "source_type": "md",
            "content_b64": base64.b64encode(b"# hi").decode()}
    # 绑定 user-c2 为 C2（P4 功能级）→ 写文档需 P3 → 403
    r = _bind(c, "user-c2", "C2", "t1")
    assert r.status_code == 200
    resp = c.post("/documents/ingest", json=body, headers={"Authorization": "Bearer user:user-c2"})
    assert resp.status_code == 403


def test_rbac_enforcement_b1_user_can_ingest(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from enterprise_ekb.app import create_app

    monkeypatch.setenv("EKB_AUTH_TOKEN", "t1")
    app = create_app(db_path=str(tmp_path / "rbac_wire2.db"))
    c = TestClient(app)
    import base64

    body = {"source_name": "y.md", "source_type": "md",
            "content_b64": base64.b64encode(b"# ok").decode()}
    r = _bind(c, "user-b1", "B1", "t1")
    assert r.status_code == 200
    resp = c.post("/documents/ingest", json=body, headers={"Authorization": "Bearer user:user-b1"})
    assert resp.status_code == 200


def test_rbac_service_token_bypasses_layer_check(monkeypatch, tmp_path):
    """服务级 token（非 user: 前缀）不做 RBAC 层判定——系统服务直通。"""
    from fastapi.testclient import TestClient

    from enterprise_ekb.app import create_app

    monkeypatch.setenv("EKB_AUTH_TOKEN", "t1")
    app = create_app(db_path=str(tmp_path / "rbac_wire3.db"))
    c = TestClient(app)
    import base64

    body = {"source_name": "z.md", "source_type": "md",
            "content_b64": base64.b64encode(b"# svc").decode()}
    resp = c.post("/documents/ingest", json=body, headers={"Authorization": "Bearer t1"})
    assert resp.status_code == 200
