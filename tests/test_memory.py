from app.services.memory.session_memory import SessionMemory
from app.api.routes.query import _augment_query_with_memory, _is_persistent_follow_up
from app.core.schemas import MemoryRecord
from app.services.agents.context_agent import ContextAgent
from datetime import datetime


def test_session_memory_tracks_turns_and_entities():
    memory = SessionMemory(max_turns=2)
    memory.add_turn("session-1", "What did Apple say?", "Apple discussed iPhone demand in Europe.")
    memory.add_turn("session-1", "And Microsoft?", "Microsoft highlighted Azure growth.")
    entities = memory.get_recent_entities("session-1")
    assert "Apple" in entities
    assert "Microsoft" in entities
    assert len(memory.get_recent_turns("session-1")) == 2


def test_persistent_context_marks_followup_without_process_memory():
    context = {
        "recent_entities": ["Termination Clause", "NovaTech"],
        "recent_messages": [{"role": "user", "content": "Explain the Termination Clause in the NovaTech contract."}],
    }

    assert _is_persistent_follow_up("What about it?", context) is True
    rewritten = _augment_query_with_memory("what about it", "follow_up", SessionMemory(), "session-1", context)

    assert "Termination Clause" in rewritten
    assert "NovaTech" in rewritten


def test_persistent_context_can_fallback_to_recent_messages():
    context = {
        "recent_entities": [],
        "recent_messages": [{"role": "user", "content": "Compare indemnity and liability in the vendor contract."}],
    }

    rewritten = _augment_query_with_memory("and the risk?", "follow_up", SessionMemory(), "session-1", context)

    assert "vendor contract" in rewritten


class _MemoryStore:
    def __init__(self):
        self.memories = []

    def list_chat_messages(self, _session_id, limit=12):
        return []

    def list_memory(self, _session_id, limit=12):
        return self.memories[-limit:]

    def list_workspace_memory(self, workspace_id, objective_profile=None, memory_type=None, limit=50):
        return [
            MemoryRecord(
                memory_id="document:1",
                session_id="document:1",
                workspace_id=workspace_id,
                user_id="system",
                objective_profile=objective_profile or "legal",
                memory_type=memory_type or "document",
                content="Document contract.pdf: risks: Termination, Liability.",
                entities=["Termination", "Liability"],
                metadata={"document_id": "doc-1", "risk_topics": ["Termination", "Liability"]},
                created_at=datetime.utcnow(),
            )
        ]

    def add_chat_message(self, *_args, **_kwargs):
        return None

    def upsert_memory(self, record):
        self.memories.append(record)


def test_context_agent_loads_document_memory():
    context, step = ContextAgent(_MemoryStore(), SessionMemory()).build(
        session_id="session-1",
        workspace_id="workspace-1",
        objective_profile="legal",
        user_goal=None,
    )

    assert context["document_memories"]
    assert "Termination" in context["recent_entities"]
    assert "document memories" in step.output_summary


def test_context_agent_persists_user_goal_as_long_term_memory():
    store = _MemoryStore()
    agent = ContextAgent(store, SessionMemory())

    agent.remember_turn(
        session_id="session-1",
        workspace_id="workspace-1",
        objective_profile="research",
        question="Help me study charts",
        answer="We will focus on chart evidence.",
        user_goal="Prepare for exam revision",
    )
    context, _ = agent.build(
        session_id="session-1",
        workspace_id="workspace-1",
        objective_profile="research",
        user_goal=None,
    )

    assert context["user_goal"] == "Prepare for exam revision"
    assert any(memory.memory_type == "long_term" for memory in store.memories)
