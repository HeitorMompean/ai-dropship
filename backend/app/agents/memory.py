"""Conversation memory and context storage for AI agents."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


class ConversationMemory:
    """In-memory store for agent contexts and decisions.

    In production this should be backed by Redis or the database.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decisions: List[Dict[str, Any]] = []
        self._agent_states: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._conversations: List[Dict[str, Any]] = []

    def add_decision_context(
        self,
        agent_name: str,
        decision_type: str,
        context: Dict[str, Any],
        sms_text: str,
    ) -> str:
        """Record a pending human decision in memory.

        Returns the decision ID.
        """
        decision_id = f"{agent_name}-{decision_type}-{datetime.utcnow().timestamp()}"
        entry = {
            "id": decision_id,
            "agent_name": agent_name,
            "decision_type": decision_type,
            "context": context,
            "sms_text": sms_text,
            "status": "pending",
            "owner_reply": None,
            "created_at": datetime.utcnow().isoformat(),
        }
        with self._lock:
            self._decisions.append(entry)
        logger.info("Decision context stored: %s", decision_id)
        return decision_id

    def get_pending_decisions(self, agent_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return pending decision entries, optionally filtered by agent."""
        with self._lock:
            pending = [d for d in self._decisions if d["status"] == "pending"]
        if agent_name:
            pending = [d for d in pending if d["agent_name"] == agent_name]
        return pending

    def resolve_decision(self, decision_id: str, reply: str, action: str) -> bool:
        """Mark a decision as resolved with the owner's reply."""
        with self._lock:
            for d in self._decisions:
                if d["id"] == decision_id:
                    d["status"] = "resolved"
                    d["owner_reply"] = reply
                    d["reply_parsed_action"] = action
                    d["resolved_at"] = datetime.utcnow().isoformat()
                    logger.info("Decision %s resolved with action: %s", decision_id, action)
                    return True
        logger.warning("Decision %s not found for resolution.", decision_id)
        return False

    def add_message(self, direction: str, body: str, decision_id: Optional[str] = None) -> None:
        """Record an SMS or chat message."""
        entry = {
            "direction": direction,
            "body": body,
            "decision_id": decision_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        with self._lock:
            self._conversations.append(entry)

    def get_conversation_history(
        self, decision_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Retrieve conversation history, optionally filtered by decision."""
        with self._lock:
            messages = self._conversations
        if decision_id:
            messages = [m for m in messages if m.get("decision_id") == decision_id]
        return messages[-limit:]

    def update_agent_state(self, agent_name: str, state: Dict[str, Any]) -> None:
        """Update the runtime state for an agent."""
        with self._lock:
            self._agent_states[agent_name].update(state)
            self._agent_states[agent_name]["updated_at"] = datetime.utcnow().isoformat()

    def get_agent_state(self, agent_name: str) -> Dict[str, Any]:
        """Get the current runtime state of an agent."""
        with self._lock:
            return dict(self._agent_states.get(agent_name, {}))

    def get_all_agent_states(self) -> Dict[str, Dict[str, Any]]:
        """Return states for all known agents."""
        with self._lock:
            return dict(self._agent_states)


conversation_memory = ConversationMemory()
