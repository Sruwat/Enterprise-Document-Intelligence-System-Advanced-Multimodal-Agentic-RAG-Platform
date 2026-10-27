from app.services.memory.session_memory import SessionMemory
from app.services.router.intent_classifier import HybridIntentClassifier


def test_router_detects_comparison():
    router = HybridIntentClassifier()
    decision = router.route("Compare revenue and profit across both reports")
    assert decision.route == "comparison"
    assert decision.requested_top_k >= 8


def test_router_detects_follow_up_from_memory():
    memory = SessionMemory(max_turns=4)
    memory.add_turn("session-1", "What did Microsoft report?", "Microsoft reported revenue growth in Azure.")
    router = HybridIntentClassifier(memory=memory)
    result = router.classify("What about its margins?", session_id="session-1")
    assert result.intent == "follow_up"
