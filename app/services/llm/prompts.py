from __future__ import annotations


def build_grounded_prompt(
    question: str,
    contexts: list[str],
    require_citations: bool = True,
    response_preferences: dict | None = None,
) -> list[dict[str, str]]:
    preferences = response_preferences or {}
    citation_instruction = (
        "Cite evidence using [Source: filename p.X chunk_id] for every factual claim."
        if require_citations
        else "Ground the answer in the provided context."
    )
    context_block = "\n\n".join(contexts)
    system = (
        "You are a document-grounded assistant. Answer only from the supplied context. "
        "If the evidence is missing or conflicting, say you do not have enough evidence. "
        "Never invent values from an image, chart or table that are not explicitly represented in the supplied evidence."
    )
    language = preferences.get("language", "english")
    level = preferences.get("explanation_level", "normal")
    answer_mode = preferences.get("answer_mode", "answer")
    objective_profile = preferences.get("objective_profile", "general")
    analysis_mode = preferences.get("analysis_mode", "quick")
    objective_note = preferences.get("objective_note")
    user_goal = preferences.get("user_goal")
    document_memories = preferences.get("document_memories") or []
    language_instruction = {
        "hindi": "Respond in Hindi using Devanagari script.",
        "hinglish": "Respond in Hinglish using clear Roman Hindi with necessary English terms.",
        "spanish": "Respond in Spanish.",
    }.get(language, "Respond in English.")
    instructions = [
        language_instruction,
        "Preserve citations, file names, page markers, and [Source: ...] text exactly as provided; do not translate source markers.",
        f"Explanation level: {level}; use plain examples for layman and more detail for deep.",
        f"Answer mode: {answer_mode}.",
        f"Objective profile: {objective_profile}; analysis mode: {analysis_mode}.",
    ]
    if user_goal:
        instructions.append(f"User's current task goal: {user_goal}.")
    if objective_note:
        instructions.append(str(objective_note))
    if document_memories:
        memory_lines = []
        for memory in document_memories[:5]:
            metadata = memory.get("metadata", {}) if isinstance(memory, dict) else {}
            memory_lines.append(f"{metadata.get('filename') or metadata.get('document_id')}: {str(memory.get('content', ''))[:240]}")
        instructions.append("Document memory available: " + " | ".join(memory_lines))
    if objective_profile == "legal":
        instructions.append(
            "For legal/contracts, identify clauses, parties, obligations, dates, risks, and uncertainty. "
            "Do not make unsupported legal claims. Add a brief legal-advice caveat only when interpreting rights, obligations, liability, or legal risk."
        )
    elif objective_profile == "research":
        instructions.append(
            "For research-grade answers, use these headings exactly: Executive summary, Evidence, Risks, Assumptions, Final recommendation. "
            "Every evidence bullet must include a citation. Mark conflicts or missing evidence explicitly."
        )
    elif objective_profile == "enterprise":
        instructions.append("For enterprise documents, prioritize traceability, policy wording, and compliance-safe caveats.")
    if answer_mode == "scenario":
        instructions.append("Use two headings: From your document and Example scenario. Mark hypothetical content clearly.")
    if answer_mode == "quiz_me":
        instructions.append("Create questions only from the supplied evidence and provide answers separately.")
    user = f"{citation_instruction}\n{' '.join(instructions)}\n\nQuestion:\n{question}\n\nContext:\n{context_block}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_json_mode_prompt(task: str, schema_hint: dict, payload: dict) -> list[dict[str, str]]:
    system = (
        "You are a structured orchestration component. Return exactly one JSON object. "
        "Do not include markdown, explanations, or surrounding text."
    )
    user = (
        f"Task: {task}\n"
        f"Required JSON shape: {schema_hint}\n"
        f"Input payload: {payload}\n"
        "Return only valid JSON."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
