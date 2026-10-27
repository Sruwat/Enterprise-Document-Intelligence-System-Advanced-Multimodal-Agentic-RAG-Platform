from app.services.memory.session_memory import SessionMemory
from app.services.planner.query_planner import QueryPlanner


def test_planner_builds_comparison_steps():
    planner = QueryPlanner()
    plan = planner.plan("Compare Microsoft vs Google on cloud revenue", "comparison")
    assert len(plan) == 3
    assert plan[0].query is not None and "Microsoft" in plan[0].query
    assert plan[1].query is not None and "Google" in plan[1].query
    assert plan[2].type == "synthesis"


def test_planner_expands_follow_up_with_memory_entities():
    memory = SessionMemory(max_turns=4)
    memory.add_turn("session-1", "Tell me about Nvidia", "Nvidia discussed AI demand and data center growth.")
    planner = QueryPlanner(memory=memory)
    plan = planner.plan("What about margins?", "follow_up", session_id="session-1")
    assert len(plan) == 1
    assert "Nvidia" in (plan[0].query or "")
