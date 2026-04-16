from dotenv import load_dotenv
import os

from livekit import agents, rtc
from livekit.agents import AgentSession, Agent, RoomInputOptions, ChatContext
from livekit.plugins import noise_cancellation, google
from prompts import AGENT_INSTRUCTION,SESSION_INSTRUCTION
from tools import get_weather, search_web, send_email, debug_memory_sync
from mem0 import AsyncMemoryClient
from mcp_client import MCPServerSse
from mcp_client.agent_tools import MCPToolsIntegration
import json, logging
import httpx
import asyncio
load_dotenv()


class Assistant(Agent):
    def __init__(self,chat_ctx=None) -> None:
        super().__init__(instructions=AGENT_INSTRUCTION,
        tools=[get_weather, search_web, send_email, debug_memory_sync],
        chat_ctx=chat_ctx
        )

def _content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
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


def _build_realtime_model():
    model_name = os.getenv("JARVIS_GOOGLE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
    voice_name = os.getenv("JARVIS_GOOGLE_VOICE", "Charon")
    temperature = float(os.getenv("JARVIS_TEMPERATURE", "0.8"))
    logging.info("Using Google realtime model '%s' with voice '%s'", model_name, voice_name)
    return google.realtime.RealtimeModel(
        model=model_name,
        voice=voice_name,
        temperature=temperature,
    )


async def entrypoint(ctx: agents.JobContext):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger().setLevel(logging.INFO)

    pending_memory_tasks: set[asyncio.Task] = set()
    saved_items: set[str] = set()
    system_memory_prefix = "The User's name is "

    async def _save_messages_to_mem0(mem0: AsyncMemoryClient, user_id: str, messages: list[dict], source: str):
        if not messages:
            return
        try:
            logging.info("Saving %d messages to Mem0 for user '%s' from %s.", len(messages), user_id, source)
            resp = await mem0.add(messages, user_id=user_id)
            logging.info("Mem0 add response from %s: %s", source, resp)
        except Exception as e:
            logging.exception("Mem0 add failed from %s for user '%s': %s", source, user_id, e)

    async def shutdown_hook(
        chat_ctx: ChatContext,
        mem0: AsyncMemoryClient,
        memory_str: str,
        user_id: str,
    ):
        logging.info("Shutdown hook called, saving conversation to memory for user '%s'.", user_id)

        messages_formatted=[]
        logging.info(f"Chat context messages: {chat_ctx.items}")
        for item in chat_ctx.items:
            content_str = _content_to_text(item.content)

            if memory_str and memory_str in content_str:
                continue
            if content_str.startswith(system_memory_prefix):
                continue
            role = str(item.role)
            if role in ["user", "assistant"] and content_str:
                message_key = f"{role}:{content_str}"
                if message_key in saved_items:
                    continue
                saved_items.add(message_key)
                messages_formatted.append({
                     "role": role,
                     "content": content_str
                   })
        logging.info(f"Formatted messages to save: {messages_formatted}")
        if not messages_formatted:
            logging.info("No eligible messages found to save to memory.")
            return
        await _save_messages_to_mem0(mem0, user_id, messages_formatted, "shutdown_hook")


    
    use_bvc = os.getenv("JARVIS_USE_BVC", "true").lower() == "true"

    session = AgentSession(
        llm=_build_realtime_model()
    )
    # Retrieve user-specific memories and add to initial context
    user_name = os.getenv("MEM0_USER_ID", "Saathwik")
    logging.info("Initializing Mem0 client for user '%s'.", user_name)
    try:
        mem0 = AsyncMemoryClient()
        logging.info("Mem0 client initialized successfully.")
    except Exception as e:
        logging.warning("Mem0 client initialization failed: %s", e)
        mem0 = None

    memories = []

    if mem0 is None:
        results = {"results": []}
    else:
        try:
            logging.info("Fetching memories from Mem0 for user '%s'.", user_name)
            # Mem0 v2 memories endpoint expects non-empty filters payload.
            results = await mem0.get_all(filters={"user_id": user_name})
            result_count = len(results.get("results", [])) if isinstance(results, dict) else 0
            logging.info("Mem0 fetch successful for user '%s'. Retrieved %d memories.", user_name, result_count)
        except httpx.HTTPStatusError as e:
            err_body = ""
            if e.response is not None:
                err_body = e.response.text
            logging.warning(
                "Mem0 get_all failed for user '%s': %s | response=%s",
                user_name,
                e,
                err_body,
            )
            results = {"results": []}
        except Exception as e:
            logging.warning("Mem0 unavailable while fetching memories for '%s': %s", user_name, e)
            results = {"results": []}
    initial_ctx=ChatContext()
    memory_str=''

    if results:
        memories = [
            {
                "memory":result["memory"],
                "updated_at":result["updated_at"]
            }
            for result in results.get("results", [])
        ]
    memory_str=json.dumps(memories,indent=4)
    logging.info(f"Memories retrieved for user '{user_name}': {memory_str}")
    initial_ctx.add_message(
        role="assistant",
        content=f"The User's name is {user_name} and this is relevant context about him: {memory_str}"
    )


    room_input_options = (
        RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
            video_enabled=True,
        )
        if use_bvc 
        else RoomInputOptions(video_enabled=True)
    )

    mcp_server= MCPServerSse(
        params={"url": os.environ.get("N8N_MCP_SERVER_URL")},
        cache_tools_list=True,
        name="SSE MCP SERVER",
    )

    agent = await MCPToolsIntegration.create_agent_with_tools(
        agent_class=Assistant, agent_kwargs={"chat_ctx": initial_ctx}, 
        mcp_server=[mcp_server])

    await ctx.connect()

    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=room_input_options,
    )

    if mem0 is not None:
        @session.on("conversation_item_added")
        def _on_conversation_item_added(ev):
            try:
                item = ev.item
                role = str(getattr(item, "role", ""))
                if role not in ["user", "assistant"]:
                    return

                content_str = _content_to_text(getattr(item, "content", ""))
                if not content_str or content_str.startswith(system_memory_prefix):
                    return
                if memory_str and memory_str in content_str:
                    return

                message_key = f"{role}:{content_str}"
                if message_key in saved_items:
                    return
                saved_items.add(message_key)

                task = asyncio.create_task(
                    _save_messages_to_mem0(
                        mem0,
                        user_name,
                        [{"role": role, "content": content_str}],
                        "conversation_item_added",
                    ),
                    name="mem0_save_message",
                )
                pending_memory_tasks.add(task)
                task.add_done_callback(lambda t: pending_memory_tasks.discard(t))
            except Exception as e:
                logging.exception("Failed to handle conversation_item_added for memory: %s", e)

    await session.generate_reply(
        instructions=SESSION_INSTRUCTION
    )
    
    if mem0 is not None:
        ctx.add_shutdown_callback(
            lambda: shutdown_hook(session.agent.chat_ctx, mem0, memory_str, user_name)
        )
        async def _await_pending_memory_tasks():
            if not pending_memory_tasks:
                return
            logging.info("Awaiting %d pending memory task(s) before shutdown.", len(pending_memory_tasks))
            await asyncio.gather(*list(pending_memory_tasks), return_exceptions=True)
        ctx.add_shutdown_callback(_await_pending_memory_tasks)
    else:
        logging.info("Skipping shutdown memory save callback because Mem0 client is unavailable.")


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(entrypoint_fnc=entrypoint)
    )
