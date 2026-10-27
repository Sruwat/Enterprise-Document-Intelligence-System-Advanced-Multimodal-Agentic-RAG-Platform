from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from app.core.schemas import AgentStep, MemoryRecord, ObjectiveProfile


class ContextAgent:
    def __init__(self, metadata_store, session_memory) -> None:
        self.metadata_store = metadata_store
        self.session_memory = session_memory

    def build(
        self,
        *,
        session_id: str,
        workspace_id: str,
        objective_profile: ObjectiveProfile,
        user_goal: str | None,
    ) -> tuple[dict[str, Any], AgentStep]:
        messages = self.metadata_store.list_chat_messages(session_id, limit=12) if session_id else []
        memories = self.metadata_store.list_memory(session_id, limit=12) if session_id else []
        document_memories = self._workspace_document_memory(workspace_id, objective_profile)
        volatile_turns = self.session_memory.get_recent_turns(session_id) if session_id else []
        entities = self._unique(
            [
                *[entity for memory in memories for entity in memory.entities],
                *[entity for memory in document_memories for entity in memory.entities],
                *[entity for turn in volatile_turns for entity in turn.entities],
            ]
        )
        context = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "objective_profile": objective_profile,
            "user_goal": user_goal or self._latest_goal(memories),
            "recent_messages": [message.model_dump() for message in messages],
            "memory_summaries": [memory.model_dump() for memory in memories],
            "document_memories": [memory.model_dump() for memory in document_memories],
            "recent_entities": entities[:12],
        }
        step = AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="ContextAgent",
            action="build_user_task_context",
            output_summary=f"Loaded {len(messages)} messages, {len(memories)} chat memory records, {len(document_memories)} document memories, {len(entities[:12])} entities.",
            metadata={"objective_profile": objective_profile, "has_user_goal": bool(user_goal)},
        )
        return context, step

    def remember_turn(
        self,
        *,
        session_id: str,
        workspace_id: str,
        objective_profile: ObjectiveProfile,
        question: str,
        answer: str,
        user_goal: str | None = None,
        user_id: str = "local-user",
        input_language: str = "auto",
        response_language: str = "auto",
        interpreted_query: str | None = None,
    ) -> None:
        if not session_id:
            return
        self.metadata_store.add_chat_message(
            session_id,
            workspace_id,
            "user",
            question,
            {"language": input_language, "input_language": input_language, "interpreted_query": interpreted_query},
        )
        self.metadata_store.add_chat_message(
            session_id,
            workspace_id,
            "assistant",
            answer,
            {"language": response_language, "response_language": response_language, "input_language": input_language},
        )
        content = self._summarize_turn(question, answer)
        entities = self._extract_entities(f"{question} {answer}")
        self.metadata_store.upsert_memory(
            MemoryRecord(
                memory_id=str(uuid.uuid4()),
                session_id=session_id,
                workspace_id=workspace_id,
                user_id=user_id,
                objective_profile=objective_profile,
                memory_type="short_term",
                content=content,
                entities=entities,
                metadata={
                    "question": question[:500],
                    "answer_preview": answer[:500],
                    "input_language": input_language,
                    "response_language": response_language,
                    "interpreted_query": interpreted_query,
                },
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        if user_goal:
            self.metadata_store.upsert_memory(
                MemoryRecord(
                    memory_id=f"goal:{session_id}",
                    session_id=session_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    objective_profile=objective_profile,
                    memory_type="long_term",
                    content=f"Current user goal: {user_goal.strip()}",
                    entities=self._extract_entities(user_goal),
                    metadata={"user_goal": user_goal.strip(), "source": "query_request"},
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )

    @staticmethod
    def _latest_goal(memories: list[MemoryRecord]) -> str | None:
        for memory in reversed(memories):
            goal = memory.metadata.get("user_goal")
            if goal:
                return str(goal)
        return None

    def _workspace_document_memory(self, workspace_id: str, objective_profile: ObjectiveProfile) -> list[MemoryRecord]:
        list_workspace_memory = getattr(self.metadata_store, "list_workspace_memory", None)
        if not callable(list_workspace_memory):
            return []
        return list_workspace_memory(workspace_id, objective_profile=objective_profile, memory_type="document", limit=12)

    @staticmethod
    def _summarize_turn(question: str, answer: str) -> str:
        answer_preview = re.sub(r"\s+", " ", answer).strip()[:360]
        return f"User asked: {question.strip()} | Aiwana answered: {answer_preview}"

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        tokens = re.findall(r"\b[A-Z][a-zA-Z0-9&.-]+(?:\s+[A-Z][a-zA-Z0-9&.-]+)*\b", text)
        return ContextAgent._unique([token.strip() for token in tokens if len(token.strip()) >= 3])

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        return unique
