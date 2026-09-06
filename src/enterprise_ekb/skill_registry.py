from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from enterprise_ekb.schemas import SkillManifest, SkillRiskLevel, SkillStage

if TYPE_CHECKING:
    from enterprise_ekb.storage import SQLiteControlPlaneStore


@dataclass(frozen=True)
class StoredSkill:
    manifest: SkillManifest
    stage: SkillStage


class SkillRegistry:
    def __init__(self, store: SQLiteControlPlaneStore | None = None) -> None:
        self._skills: dict[tuple[str, str], StoredSkill] = {}
        self._store = store
        if self._store is not None:
            for row in self._store.list_skills():
                key = (row.manifest.skill_name, row.manifest.version)
                self._skills[key] = StoredSkill(
                    manifest=row.manifest,
                    stage=row.stage,
                )

    def register(self, manifest: SkillManifest) -> StoredSkill:
        key = (manifest.skill_name, manifest.version)
        if key in self._skills:
            raise ValueError("skill version already exists")
        stored = StoredSkill(manifest=manifest, stage=SkillStage.draft)
        if self._store is not None:
            self._store.create_skill(manifest=manifest, stage=SkillStage.draft)
        self._skills[key] = stored
        return stored

    def get(self, skill_name: str, version: str) -> StoredSkill:
        key = (skill_name, version)
        if key not in self._skills:
            raise KeyError("skill not found")
        return self._skills[key]

    def promote(self, skill_name: str, version: str, target: SkillStage) -> StoredSkill:
        current = self.get(skill_name, version)
        if not self._is_valid_transition(current.stage, target):
            raise ValueError("invalid stage transition")
        self._validate_gate_requirements(current, target)
        updated = StoredSkill(manifest=current.manifest, stage=target)
        if self._store is not None:
            self._store.update_skill_stage(skill_name=skill_name, version=version, stage=target)
        self._skills[(skill_name, version)] = updated
        return updated

    @staticmethod
    def _is_valid_transition(current: SkillStage, target: SkillStage) -> bool:
        transition_table: dict[SkillStage, set[SkillStage]] = {
            SkillStage.draft: {SkillStage.review},
            SkillStage.review: {SkillStage.staging, SkillStage.deprecated},
            SkillStage.staging: {SkillStage.production, SkillStage.deprecated},
            SkillStage.production: {SkillStage.deprecated},
            SkillStage.deprecated: set(),
        }
        return target in transition_table[current]

    @staticmethod
    def _validate_gate_requirements(stored: StoredSkill, target: SkillStage) -> None:
        manifest = stored.manifest
        if target in {SkillStage.staging, SkillStage.production}:
            if not manifest.allowed_tools:
                raise ValueError("allowed_tools cannot be empty for staging/production")
            if not manifest.residency_scope:
                raise ValueError("residency_scope cannot be empty for staging/production")
        if target is SkillStage.production and manifest.risk_level is SkillRiskLevel.high:
            if "security-approved" not in manifest.changelog:
                raise ValueError("high risk skill requires security-approved tag in changelog")
