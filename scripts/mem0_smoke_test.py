"""Manual smoke test for Mem0 connectivity (hits the live API).

Run from the repo root:  python scripts/mem0_smoke_test.py
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mem0 import MemoryClient

from config import settings

logger = logging.getLogger("mem0-smoke-test")


def add_memory(mem0: MemoryClient) -> None:
    messages = [
        {"role": "user", "content": "My favorite food is biriyani."},
        {"role": "assistant", "content": "Noted, Sir. Any particular kind?"},
        {"role": "user", "content": "I like chicken biriyani the most."},
        {"role": "assistant", "content": "Chicken biriyani it is."},
    ]
    mem0.add(messages, user_id=settings.mem0_user_id)


def get_memory_by_query(mem0: MemoryClient) -> str:
    query = "What is the user's favorite food?"
    response = mem0.search(query, filters={"user_id": settings.mem0_user_id})
    memories = [
        {"memory": r["memory"], "updated_at": r.get("updated_at")}
        for r in response.get("results", [])
    ]
    memories_str = json.dumps(memories, indent=4)
    logger.info("Memories retrieved for query '%s': %s", query, memories_str)
    return memories_str


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = MemoryClient()
    get_memory_by_query(client)
