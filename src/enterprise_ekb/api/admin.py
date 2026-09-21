"""Admin RBAC routes (P0-④): role catalog + user-role binding management.

Follows the bounded-context route-module pattern of ``enterprise_ekb.api.skills``:
``routes(ctx)`` closes over the shared ``ControlPlaneContext``. The module-level
``rbac`` service (store-less) backs the public role catalog; a store-bound
service is built per application inside ``routes``.
"""

from __future__ import annotations

from typing import Any

from litestar import Request, delete, get, post
from litestar.exceptions import HTTPException
from pydantic import BaseModel

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.rbac import RBACService


class UserRoleBinding(BaseModel):
    """Request body for binding a user to an RBAC role."""

    user_id: str
    role: str
    tenant_id: str = "group"
    department: str = ""


#: Store-less instance: serves the static 12-role catalog only.
rbac = RBACService(store=None)


def routes(ctx: ControlPlaneContext) -> list:
    service = RBACService(store=ctx.store)

    @get("/admin/rbac/roles", status_code=200)
    def list_roles() -> list[dict[str, Any]]:
        """Public read-only catalog of the 12 roles and their permission layers."""
        return rbac.describe_roles()

    @post("/admin/rbac/users", status_code=200, sync_to_thread=True)
    def assign_user_role(data: UserRoleBinding, request: Request) -> dict[str, str]:
        ctx._require_admin_auth(request)
        try:
            service.assign_role(
                user_id=data.user_id,
                role=data.role,
                tenant_id=data.tenant_id,
                department=data.department,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        ctx.store.enqueue_outbox(
            event_type="rbac.user.assigned",
            payload={
                "user_id": data.user_id,
                "role": data.role,
                "tenant_id": data.tenant_id,
                "department": data.department,
            },
        )
        return {"user_id": data.user_id, "role": data.role}

    @get("/admin/rbac/users", status_code=200, sync_to_thread=True)
    def list_bound_users(request: Request) -> list[dict[str, Any]]:
        ctx._require_admin_auth(request)
        return service.list_users()

    @delete("/admin/rbac/users/{user_id:str}", status_code=200, sync_to_thread=True)
    def delete_bound_user(user_id: str, request: Request) -> dict[str, Any]:
        ctx._require_admin_auth(request)
        deleted = service.delete_user(user_id)
        return {"user_id": user_id, "deleted": deleted}

    return [list_roles, assign_user_role, list_bound_users, delete_bound_user]
