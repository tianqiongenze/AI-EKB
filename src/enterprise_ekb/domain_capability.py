from __future__ import annotations

from dataclasses import dataclass

from enterprise_ekb.schemas import (
    BusinessCapabilityManifest,
    BusinessDomain,
    CapabilityMaturity,
    DomainCapabilitySearchResult,
    DomainCoverageItem,
    DomainCoverageResponse,
)


@dataclass(frozen=True)
class DomainBaseline:
    domain: BusinessDomain
    required_capabilities: tuple[str, ...]


DOMAIN_BASELINES: tuple[DomainBaseline, ...] = (
    DomainBaseline(BusinessDomain.strategy, ("decision_dashboard", "risk_warning", "kpi_monitoring")),
    DomainBaseline(BusinessDomain.rnd, ("project_process_library", "version_control_governance", "design_reuse")),
    DomainBaseline(BusinessDomain.manufacturing, ("sop_knowledge", "yield_optimization", "equipment_tuning")),
    DomainBaseline(BusinessDomain.quality, ("defect_graph", "quality_traceability", "supplier_quality_control")),
    DomainBaseline(BusinessDomain.procurement, ("supplier_lifecycle", "pricing_model", "purchase_planning")),
    DomainBaseline(BusinessDomain.aftersales, ("repair_knowledge", "complaint_playbook", "service_kpi")),
    DomainBaseline(BusinessDomain.hr, ("recruitment_process", "training_path", "performance_management")),
    DomainBaseline(BusinessDomain.finance, ("budget_control", "risk_control", "compliance_governance")),
    DomainBaseline(BusinessDomain.materials, ("inventory_optimization", "material_planning", "warehouse_process")),
    DomainBaseline(BusinessDomain.marketing, ("user_segmentation", "sales_playbook", "customer_retention")),
    DomainBaseline(BusinessDomain.iot, ("telematics_data_hub", "firmware_lifecycle", "edge_diagnostics")),
    DomainBaseline(BusinessDomain.knowledge_graph, ("traceability_network", "process_reasoning", "impact_analysis")),
)


def _find_baseline(domain: BusinessDomain) -> DomainBaseline:
    for baseline in DOMAIN_BASELINES:
        if baseline.domain == domain:
            return baseline
    return DomainBaseline(domain=domain, required_capabilities=tuple())


class DomainCapabilityService:
    def __init__(self, store) -> None:
        self._store = store

    def upsert(self, capability: BusinessCapabilityManifest) -> int:
        return self._store.upsert_business_capability(capability)

    def search(self, domain: BusinessDomain | None = None, query: str | None = None, limit: int = 100) -> DomainCapabilitySearchResult:
        items = self._store.list_business_capabilities(domain=domain, query=query, limit=limit)
        return DomainCapabilitySearchResult(count=len(items), items=items)

    def coverage(self) -> DomainCoverageResponse:
        all_items = self._store.list_business_capabilities(limit=2000)
        by_domain: dict[BusinessDomain, list[BusinessCapabilityManifest]] = {}
        for item in all_items:
            by_domain.setdefault(item.domain, []).append(item)

        coverage_items: list[DomainCoverageItem] = []
        met_domains = 0
        partial_domains = 0
        not_met_domains = 0

        for baseline in DOMAIN_BASELINES:
            implemented = by_domain.get(baseline.domain, [])
            implemented_types = {item.capability_type for item in implemented}
            missing = [cap for cap in baseline.required_capabilities if cap not in implemented_types]
            required_count = len(baseline.required_capabilities)
            implemented_count = required_count - len(missing)
            planned_count = sum(1 for item in implemented if item.maturity == CapabilityMaturity.planned)

            if required_count == 0 or implemented_count == 0:
                status = "not_met"
                not_met_domains += 1
            elif implemented_count < required_count:
                status = "partial"
                partial_domains += 1
            else:
                status = "met"
                met_domains += 1

            coverage_items.append(
                DomainCoverageItem(
                    domain=baseline.domain,
                    required_count=required_count,
                    implemented_count=implemented_count,
                    planned_count=planned_count,
                    status=status,
                    missing_capabilities=missing,
                    implemented_capabilities=sorted(implemented_types),
                )
            )

        return DomainCoverageResponse(
            summary={
                "met": met_domains,
                "partial": partial_domains,
                "not_met": not_met_domains,
                "total": len(DOMAIN_BASELINES),
            },
            items=coverage_items,
        )


def default_domain_bootstrap(owner: str = "domain-pmo") -> list[BusinessCapabilityManifest]:
    items: list[BusinessCapabilityManifest] = []
    for baseline in DOMAIN_BASELINES:
        for capability_type in baseline.required_capabilities:
            items.append(
                BusinessCapabilityManifest(
                    domain=baseline.domain,
                    capability_type=capability_type,
                    title=f"{baseline.domain.value}:{capability_type}",
                    description=f"Baseline capability for {baseline.domain.value}",
                    owner=owner,
                    maturity=CapabilityMaturity.planned,
                    tags=[baseline.domain.value, "baseline"],
                    metadata={"source": "yadea-requirements-draft"},
                )
            )
    return items
