"""Mem0-backed long-term memory for J.A.R.V.I.S.

Encapsulates loading memories at session start and saving new
conversation exchanges as they happen. Messages are buffered and flushed
as user/assistant pairs (Mem0 extracts far better facts from exchanges
than from isolated messages), deduplicated by chat-item id so legitimate
repeated utterances ("yes", "ok") are not dropped.
"""

import asyncio
import json
import logging
from typing import Any

from mem0 import AsyncMemoryClient

from config import settings

logger = logging.getLogger("jarvis.memory")

# Prefix used to recognize (and never re-save) the injected context message.
CONTEXT_PREFIX = "[memory-context]"


def content_to_text(content: Any) -> str:
    """Normalize a LiveKit chat item's content into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("transcript") or ""
                parts.append(str(text))
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None) or ""
                parts.append(str(text))
        return "".join(parts).strip()
    return str(content).strip()


class MemoryManager:
    """Owns the Mem0 client, dedupe state, and save/load logic."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self._client: AsyncMemoryClient | None = None
        self._seen_ids: set[str] = set()
        self._buffer: list[dict[str, str]] = []
        self._pending: set[asyncio.Task] = set()
        try:
            self._client = AsyncMemoryClient()
            logger.info("Mem0 client initialized for user '%s'.", user_id)
        except Exception as e:
            logger.warning("Mem0 client initialization failed, memory disabled: %s", e)

    @property
    def available(self) -> bool:
        return self._client is not None

    async def build_context_message(self) -> str | None:
        """Fetch stored memories and format them as a system-context string."""
        if self._client is None:
            return None
        try:
            # Mem0 v2 memories endpoint expects a non-empty filters payload.
            results = await self._client.get_all(filters={"user_id": self.user_id})
        except Exception as e:
            logger.warning("Mem0 fetch failed for user '%s': %s", self.user_id, e)
            return None

        items = results.get("results", []) if isinstance(results, dict) else []
        memories = [
            {"memory": r.get("memory", ""), "updated_at": r.get("updated_at", "")}
            for r in items
            if r.get("memory")
        ]
        # Most recent first, capped so the context can't grow unbounded.
        memories.sort(key=lambda m: m.get("updated_at") or "", reverse=True)
        memories = memories[: settings.memory_limit]
        logger.info("Loaded %d memories for user '%s'.", len(memories), self.user_id)

        if not memories:
            return f"{CONTEXT_PREFIX} The user's name is {self.user_id}. No stored memories yet."
        return (
            f"{CONTEXT_PREFIX} The user's name is {self.user_id}. "
            f"Context from previous conversations, most recent first: "
            f"{json.dumps(memories, ensure_ascii=False)}"
        )

    def on_conversation_item(self, item: Any) -> None:
        """Handle a conversation_item_added event (sync, schedules async save)."""
        if self._client is None:
            return
        role = str(getattr(item, "role", ""))
        if role not in ("user", "assistant"):
            return
        content = content_to_text(getattr(item, "content", None))
        if not content or content.startswith(CONTEXT_PREFIX):
            return

        # Dedupe by chat-item id, not by content, so repeated utterances survive.
        item_id = str(getattr(item, "id", None) or f"{role}:{content}")
        if item_id in self._seen_ids:
            return
        self._seen_ids.add(item_id)

        self._buffer.append({"role": role, "content": content})
        # An assistant turn completes a user/assistant exchange -> flush the pair.
        if role == "assistant":
            self.flush()

    def flush(self) -> None:
        """Ship the current buffer to Mem0 in a background task."""
        if self._client is None or not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        task = asyncio.create_task(self._save(batch), name="mem0_save")
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _save(self, messages: list[dict[str, str]]) -> None:
        try:
            logger.info("Saving %d message(s) to Mem0 for user '%s'.", len(messages), self.user_id)
            resp = await self._client.add(messages, user_id=self.user_id)
            logger.debug("Mem0 add response: %s", resp)
        except Exception:
            logger.exception("Mem0 add failed for user '%s'.", self.user_id)

    async def aclose(self) -> None:
        """Flush remaining messages and wait for in-flight saves.

        Register this as a LiveKit shutdown callback.
        """
        if self._client is None:
            return
        self.flush()
        if self._pending:
            logger.info("Awaiting %d pending memory task(s) before shutdown.", len(self._pending))
            await asyncio.gather(*list(self._pending), return_exceptions=True)
