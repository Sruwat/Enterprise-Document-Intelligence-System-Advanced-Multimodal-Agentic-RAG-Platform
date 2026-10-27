from app.services.router.intent_classifier import HybridIntentClassifier


class _JsonLLM:
    provider_name = "groq"

    def __init__(self, payload: str):
        self.payload = payload

    def generate(self, *_args, **_kwargs):
        return self.payload


def test_router_accepts_valid_structured_json_route():
    router = HybridIntentClassifier(
        llm_provider=_JsonLLM(
            '{"intent":"chart_analysis","confidence":0.91,"reason":"chart requested","retrieval_strategy":"visual","requested_top_k":8,"needs_clarification":false}'
        )
    )

    result = router.classify("Explain the trend in this confusing graph")

    assert result.intent == "chart_analysis"
    assert result.used_llm_refinement is True
    assert result.signals["structured_route_plan"]["retrieval_strategy"] == "visual"


def test_router_falls_back_when_structured_json_is_invalid():
    router = HybridIntentClassifier(llm_provider=_JsonLLM("not-json"))

    result = router.classify("Compare revenue versus cost")

    assert result.intent == "comparison"
    assert result.used_llm_refinement is False
