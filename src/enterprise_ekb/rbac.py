"""P0-④ RBAC: 12 roles x 4 permission layers (spec §1.2.2).

Role model (docs/sources/ai-knowledge-management-4r-v5-architecture.zh-CN.md):

- 9 human roles:      A1/A2/A3 (admin tier), B1/B2/B3 (editor tier), C1/C2/C3 (consumer tier)
- 3 non-human roles:  D1 AI Agent, D2 System Service, D3 External Integration
- 4 permission layers: P1 system, P2 application, P3 data, P4 function

Layer mapping (spec edges): A1→P1, A2/A3→P2, B1/B2/B3→P3, C1/C2/C3→P4.
The spec draws NO edge from D1/D2/D3 to any P-layer, so non-human subjects
carry an empty standing layer set here — their access is granted through
scoped credentials/capabilities, not role-layer inheritance.

Hierarchical inheritance: holding layer P_n implies P_(n+1)..P4. The
``ROLE_PERMISSION_LAYERS`` table is pre-expanded so a single set-membership
check answers "does role R satisfy layer L".
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Permission layers
# ---------------------------------------------------------------------------

LAYER_SYSTEM = "P1"
LAYER_APPLICATION = "P2"
LAYER_DATA = "P3"
LAYER_FUNCTION = "P4"

#: Canonical layer order from highest (P1) to lowest (P4).
LAYER_ORDER: tuple[str, ...] = (LAYER_SYSTEM, LAYER_APPLICATION, LAYER_DATA, LAYER_FUNCTION)

ALL_LAYERS: frozenset[str] = frozenset(LAYER_ORDER)

#: Sentinel layer for roles that hold no standing layer in the hierarchy
#: (the non-human D roles, which the spec does not map to any P-layer).
NO_LAYER = ""


def layer_implies(layer: str) -> frozenset[str]:
    """Return the full set of layers implied by holding ``layer``.

    Holding P_n implies P_n and every lower layer down to P4, e.g.
    ``layer_implies("P2") == {"P2", "P3", "P4"}``.

    Raises:
        ValueError: if ``layer`` is not one of P1..P4.
    """
    if layer not in LAYER_ORDER:
        raise ValueError(f"unknown permission layer: {layer!r}; expected one of {', '.join(LAYER_ORDER)}")
    index = LAYER_ORDER.index(layer)
    return frozenset(LAYER_ORDER[index:])


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class RoleCode:
    """String constants for the 12 role codes (str, not Enum — JSON friendly)."""

    SYSTEM_ADMIN = "A1"
    KNOWLEDGE_ADMIN = "A2"
    DEPARTMENT_ADMIN = "A3"
    SENIOR_EDITOR = "B1"
    CONTENT_EDITOR = "B2"
    REVIEWER = "B3"
    EXPERT_USER = "C1"
    REGULAR_USER = "C2"
    GUEST_USER = "C3"
    AI_AGENT = "D1"
    SYSTEM_SERVICE = "D2"
    EXTERNAL_INTEGRATION = "D3"


ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    RoleCode.SYSTEM_ADMIN: {
        "code": "A1",
        "name": "系统管理员",
        "layer": LAYER_SYSTEM,
        "description": "System Admin — owns platform-wide configuration, tenancy and security; highest authority (P1).",
        "human": True,
    },
    RoleCode.KNOWLEDGE_ADMIN: {
        "code": "A2",
        "name": "知识管理员",
        "layer": LAYER_APPLICATION,
        "description": "Knowledge Admin — governs the knowledge base at application level: taxonomies, lifecycle, quality (P2).",
        "human": True,
    },
    RoleCode.DEPARTMENT_ADMIN: {
        "code": "A3",
        "name": "部门管理员",
        "layer": LAYER_APPLICATION,
        "description": "Department Admin — manages users, roles and content for their department scope (P2).",
        "human": True,
    },
    RoleCode.SENIOR_EDITOR: {
        "code": "B1",
        "name": "高级编辑者",
        "layer": LAYER_DATA,
        "description": "Senior Editor — creates, curates and approves knowledge assets; may delegate to editors (P3).",
        "human": True,
    },
    RoleCode.CONTENT_EDITOR: {
        "code": "B2",
        "name": "内容编辑者",
        "layer": LAYER_DATA,
        "description": "Content Editor — authors and edits knowledge content within assigned scopes (P3).",
        "human": True,
    },
    RoleCode.REVIEWER: {
        "code": "B3",
        "name": "审核人员",
        "layer": LAYER_DATA,
        "description": "Reviewer — reviews and approves/rejects content before publication (P3).",
        "human": True,
    },
    RoleCode.EXPERT_USER: {
        "code": "C1",
        "name": "专家用户",
        "layer": LAYER_FUNCTION,
        "description": "Expert User — advanced consumption: feedback, annotations, expert search tooling (P4).",
        "human": True,
    },
    RoleCode.REGULAR_USER: {
        "code": "C2",
        "name": "普通用户",
        "layer": LAYER_FUNCTION,
        "description": "Regular User — standard knowledge search and consumption (P4); the platform default role.",
        "human": True,
    },
    RoleCode.GUEST_USER: {
        "code": "C3",
        "name": "访客用户",
        "layer": LAYER_FUNCTION,
        "description": "Guest User — restricted read-only access to published knowledge (P4).",
        "human": True,
    },
    RoleCode.AI_AGENT: {
        "code": "D1",
        "name": "AI Agent",
        "layer": NO_LAYER,
        "description": "AI Agent — non-human principal; no standing permission layer, access via scoped grants.",
        "human": False,
    },
    RoleCode.SYSTEM_SERVICE: {
        "code": "D2",
        "name": "系统服务",
        "layer": NO_LAYER,
        "description": "System Service — non-human principal; internal service identity, access via scoped grants.",
        "human": False,
    },
    RoleCode.EXTERNAL_INTEGRATION: {
        "code": "D3",
        "name": "外部集成",
        "layer": NO_LAYER,
        "description": "External Integration — non-human principal; third-party integration identity, access via scoped grants.",
        "human": False,
    },
}

#: Declared top layer per role, expanded through ``layer_implies`` so that
#: holding P_n implies every layer down to P4 (hierarchical inheritance).
_ROLE_TOP_LAYERS: dict[str, set[str]] = {
    RoleCode.SYSTEM_ADMIN: {LAYER_SYSTEM},
    RoleCode.KNOWLEDGE_ADMIN: {LAYER_APPLICATION},
    RoleCode.DEPARTMENT_ADMIN: {LAYER_APPLICATION},
    RoleCode.SENIOR_EDITOR: {LAYER_DATA},
    RoleCode.CONTENT_EDITOR: {LAYER_DATA},
    RoleCode.REVIEWER: {LAYER_DATA},
    RoleCode.EXPERT_USER: {LAYER_FUNCTION},
    RoleCode.REGULAR_USER: {LAYER_FUNCTION},
    RoleCode.GUEST_USER: {LAYER_FUNCTION},
    RoleCode.AI_AGENT: set(),
    RoleCode.SYSTEM_SERVICE: set(),
    RoleCode.EXTERNAL_INTEGRATION: set(),
}

ROLE_PERMISSION_LAYERS: dict[str, set[str]] = {
    role: set().union(*(layer_implies(layer) for layer in top_layers)) if top_layers else set()
    for role, top_layers in _ROLE_TOP_LAYERS.items()
}

DEFAULT_ROLE = RoleCode.REGULAR_USER


def role_layers(role: str) -> frozenset[str]:
    """Effective permission layers for ``role`` (empty for unknown/D roles)."""
    return frozenset(ROLE_PERMISSION_LAYERS.get(role, ()))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PermissionDeniedError(Exception):
    """Raised when a user's role does not satisfy the required permission layer."""

    def __init__(
        self,
        user_id: str,
        role: str,
        needed_layer: str,
        message: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.role = role
        self.needed_layer = needed_layer
        if message is None:
            message = (
                f"permission denied: user {user_id!r} with role {role!r} "
                f"does not hold required layer {needed_layer!r}"
            )
        super().__init__(message)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RBACService:
    """Role assignment and layer-gated authorization against a control-plane store.

    The store contract (implemented by the control-plane persistence layer):

    - ``upsert_user(user_id: str, role: str, tenant_id: str, department: str) -> None``
    - ``get_user_role(user_id: str) -> str | None``
    - ``list_users() -> list[dict]``
    - ``delete_user(user_id: str) -> None``

    ``store`` may be ``None`` (e.g. metadata-only usage): reads then degrade to
    ``default_role`` and writes raise ``RuntimeError`` instead of crashing.
    """

    def __init__(self, store: Any = None, default_role: str = DEFAULT_ROLE) -> None:
        if default_role not in ROLE_DEFINITIONS:
            raise ValueError(f"unknown default_role: {default_role!r}; expected one of {', '.join(ROLE_DEFINITIONS)}")
        self._store = store
        self._default_role = default_role

    @property
    def default_role(self) -> str:
        return self._default_role

    def assign_role(self, user_id: str, role: str, tenant_id: str = "group", department: str = "") -> None:
        """Bind ``user_id`` to ``role`` (upsert). Raises ValueError on invalid input."""
        if not user_id or not isinstance(user_id, str):
            raise ValueError("user_id must be a non-empty string")
        if role not in ROLE_DEFINITIONS:
            raise ValueError(f"unknown role: {role!r}; expected one of {', '.join(ROLE_DEFINITIONS)}")
        if self._store is None:
            raise RuntimeError("RBAC store is not configured; cannot persist role assignment")
        self._store.upsert_user(user_id=user_id, role=role, tenant_id=tenant_id, department=department)

    def get_role(self, user_id: str) -> str:
        """Current role for ``user_id``; ``default_role`` when unknown or store-less."""
        if not user_id or not isinstance(user_id, str):
            return self._default_role
        if self._store is None:
            return self._default_role
        stored: Any = self._store.get_user_role(user_id)
        if not stored:
            return self._default_role
        return str(stored)

    def require_layers(self, user_id: str, needed_layer: str) -> None:
        """Assert that ``user_id``'s role satisfies ``needed_layer`` (with inheritance).

        Raises:
            ValueError: if ``needed_layer`` is not a valid layer code.
            PermissionDeniedError: if the user's effective layers are insufficient.
        """
        if needed_layer not in ALL_LAYERS:
            raise ValueError(f"unknown permission layer: {needed_layer!r}; expected one of {', '.join(LAYER_ORDER)}")
        role = self.get_role(user_id)
        if needed_layer not in role_layers(role):
            raise PermissionDeniedError(user_id=user_id, role=role, needed_layer=needed_layer)

    def describe_roles(self) -> list[dict[str, Any]]:
        """Full metadata for all 12 roles (fresh copies, JSON-serializable)."""
        return [
            {
                **dict(ROLE_DEFINITIONS[code]),
                "layers": sorted(ROLE_PERMISSION_LAYERS[code]),
            }
            for code in ROLE_DEFINITIONS
        ]

    # -- store passthroughs (None-safe) used by the admin API -----------------

    def list_users(self) -> list[dict[str, Any]]:
        """All user-role bindings; empty list when no store is configured."""
        if self._store is None:
            return []
        return list(self._store.list_users())

    def delete_user(self, user_id: str) -> bool:
        """Remove a binding; returns whether a store was available to do it."""
        if self._store is None:
            return False
        self._store.delete_user(user_id)
        return True
