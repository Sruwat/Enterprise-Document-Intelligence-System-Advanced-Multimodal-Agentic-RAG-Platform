from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IndustryPack:
    pack_id: str
    label: str
    objective_profile: str
    query_mode: str
    data_boundary: str
    extraction_focus: list[str]
    prompt_starters: list[str]


INDUSTRY_PACKS: tuple[IndustryPack, ...] = (
    IndustryPack(
        pack_id="legal-contracts",
        label="Legal and contracts",
        objective_profile="legal",
        query_mode="deep",
        data_boundary="confidential_by_default",
        extraction_focus=["parties", "obligations", "dates", "termination", "liability", "risks"],
        prompt_starters=["Compare obligations across these contracts.", "Find renewal, termination, and penalty risks."],
    ),
    IndustryPack(
        pack_id="finance-diligence",
        label="Finance and diligence",
        objective_profile="enterprise",
        query_mode="deep",
        data_boundary="private_workspace_recommended",
        extraction_focus=["financial tables", "KPIs", "assumptions", "variance", "risk notes", "source citations"],
        prompt_starters=["Summarize key financial risks with page citations.", "Compare revenue and margin assumptions across files."],
    ),
    IndustryPack(
        pack_id="insurance-underwriting",
        label="Insurance underwriting",
        objective_profile="enterprise",
        query_mode="balanced",
        data_boundary="restricted_documents_supported",
        extraction_focus=["submission data", "policy clauses", "claims history", "exposure", "coverage gaps"],
        prompt_starters=["Extract coverage gaps and underwriting concerns.", "Summarize this submission package for review."],
    ),
    IndustryPack(
        pack_id="healthcare-admin",
        label="Healthcare administration",
        objective_profile="enterprise",
        query_mode="balanced",
        data_boundary="no_phi_claim_without_deployment_review",
        extraction_focus=["policies", "procedures", "compliance controls", "forms", "operational evidence"],
        prompt_starters=["Find policy requirements and missing evidence.", "Summarize procedure changes with citations."],
    ),
    IndustryPack(
        pack_id="manufacturing-quality",
        label="Manufacturing and quality",
        objective_profile="enterprise",
        query_mode="balanced",
        data_boundary="plant_or_vpc_deployment_recommended",
        extraction_focus=["specifications", "SOPs", "quality deviations", "inspection tables", "root-cause notes"],
        prompt_starters=["Find deviations from this SOP.", "Compare inspection criteria across these specifications."],
    ),
    IndustryPack(
        pack_id="education-research",
        label="Education and research",
        objective_profile="research",
        query_mode="balanced",
        data_boundary="workspace_private_when_needed",
        extraction_focus=["findings", "citations", "methodology", "tables", "limitations", "open questions"],
        prompt_starters=["Create a cited literature-style summary.", "List claims, evidence, and unresolved questions."],
    ),
)


def list_industry_packs() -> list[dict]:
    return [asdict(pack) for pack in INDUSTRY_PACKS]
