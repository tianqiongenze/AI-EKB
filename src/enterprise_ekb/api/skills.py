from __future__ import annotations

from litestar import Request, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.schemas import (
    SkillManifest,
    SkillPromotionRequest,
)


def routes(ctx: ControlPlaneContext) -> list:
    @post("/skills/register", status_code=200, sync_to_thread=True)
    def register_skill(data: SkillManifest, request: Request) -> dict[str, str]:
        ctx._require_admin_auth(request)
        try:
            stored = ctx.skill_registry.register(data)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        ctx.store.enqueue_outbox(
            event_type="skill.registered",
            payload={
                "skill_name": stored.manifest.skill_name,
                "version": stored.manifest.version,
                "stage": stored.stage.value,
                "owner": stored.manifest.owner,
            },
        )
        return {
            "skill": stored.manifest.skill_name,
            "version": stored.manifest.version,
            "stage": stored.stage.value,
        }
    @post("/skills/promote", status_code=200, sync_to_thread=True)
    def promote_skill(data: SkillPromotionRequest, request: Request) -> dict[str, str]:
        ctx._require_admin_auth(request)
        try:
            stored = ctx.skill_registry.promote(
                skill_name=data.skill_name,
                version=data.version,
                target=data.target_stage,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ctx.store.enqueue_outbox(
            event_type="skill.promoted",
            payload={
                "skill_name": stored.manifest.skill_name,
                "version": stored.manifest.version,
                "stage": stored.stage.value,
            },
        )
        return {
            "skill": stored.manifest.skill_name,
            "version": stored.manifest.version,
            "stage": stored.stage.value,
        }
    return [register_skill, promote_skill]
