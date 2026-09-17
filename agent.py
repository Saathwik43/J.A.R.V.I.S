"""J.A.R.V.I.S entrypoint: wires the LiveKit session, agent, MCP tools, and memory."""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, ChatContext, RoomInputOptions, mcp
from livekit.plugins import google, noise_cancellation

from config import settings
from memory import MemoryManager
from prompts import AGENT_INSTRUCTION, SESSION_INSTRUCTION
from tools import debug_memory_sync, get_weather, search_web, send_email

load_dotenv()

logger = logging.getLogger("jarvis")


class Assistant(Agent):
    def __init__(
        self,
        chat_ctx: ChatContext | None = None,
        instructions: str = AGENT_INSTRUCTION,
    ) -> None:
        super().__init__(
            instructions=instructions,
            tools=[get_weather, search_web, send_email, debug_memory_sync],
            chat_ctx=chat_ctx,
        )


def _build_realtime_model() -> google.realtime.RealtimeModel:
    logger.info(
        "Using Google realtime model '%s' with voice '%s'.",
        settings.google_model,
        settings.google_voice,
    )
    return google.realtime.RealtimeModel(
        model=settings.google_model,
        voice=settings.google_voice,
        temperature=settings.temperature,
    )


def _build_text_llm():
    """Text LLM used by the console pipeline (Ctrl+T and typed input)."""
    if settings.llm_provider == "openai":
        from livekit.plugins import openai

        logger.info("Using OpenAI text model '%s'.", settings.openai_text_model)
        return openai.LLM(model=settings.openai_text_model, temperature=settings.temperature)

    logger.info("Using Google text model '%s'.", settings.google_text_model)
    return google.LLM(model=settings.google_text_model, temperature=settings.temperature)


def _build_console_session(mcp_servers: list[mcp.MCPServerHTTP]) -> AgentSession:
    """STT → text LLM → TTS so console text mode and mic mode both work.

    Gemini native-audio Live cannot complete typed turns; keep that model for
    real LiveKit rooms only.
    """
    from livekit.plugins import openai, silero

    if settings.llm_provider == "openai":
        tts = openai.TTS()
    else:
        tts = google.beta.GeminiTTS(voice_name=settings.google_voice)

    logger.info(
        "Console session: text LLM pipeline (provider=%s). "
        "Switch with Ctrl+T; start in text with `python agent.py console --text`.",
        settings.llm_provider,
    )
    return AgentSession(
        llm=_build_text_llm(),
        stt=openai.STT(),
        tts=tts,
        vad=silero.VAD.load(),
        mcp_servers=mcp_servers,
    )


def _build_voice_session(mcp_servers: list[mcp.MCPServerHTTP]) -> AgentSession:
    return AgentSession(
        llm=_build_realtime_model(),
        mcp_servers=mcp_servers,
    )


async def entrypoint(ctx: agents.JobContext) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console = ctx.is_fake_job()

    # --- Long-term memory -------------------------------------------------
    memory = MemoryManager(settings.mem0_user_id)
    initial_ctx = ChatContext()
    instructions = AGENT_INSTRUCTION
    context_message = await memory.build_context_message()
    if context_message:
        if console:
            # Text LLMs accept system-role history; Gemini Live does not.
            initial_ctx.add_message(role="system", content=context_message)
        else:
            instructions = f"{AGENT_INSTRUCTION}\n\n{context_message}"

    # --- MCP servers (native LiveKit support) -----------------------------
    mcp_servers: list[mcp.MCPServerHTTP] = []
    if settings.n8n_mcp_server_url:
        # Transport (SSE vs streamable HTTP) is auto-detected from the URL.
        mcp_servers.append(mcp.MCPServerHTTP(url=settings.n8n_mcp_server_url))
    else:
        logger.warning("N8N_MCP_SERVER_URL is not configured; starting without MCP tools.")

    # --- Session ----------------------------------------------------------
    session = _build_console_session(mcp_servers) if console else _build_voice_session(mcp_servers)

    # Register the memory hook BEFORE session.start so no early items are missed.
    if memory.available:

        @session.on("conversation_item_added")
        def _on_conversation_item_added(ev) -> None:
            try:
                memory.on_conversation_item(ev.item)
            except Exception:
                logger.exception("Failed to handle conversation_item_added for memory.")

        ctx.add_shutdown_callback(memory.aclose)
    else:
        logger.info("Memory is unavailable; conversation will not be persisted.")

    room_input_options = RoomInputOptions(
        noise_cancellation=noise_cancellation.BVC() if settings.use_bvc else None,
        video_enabled=settings.video_enabled,
    )

    logger.info("Connecting to LiveKit room.")
    await ctx.connect()
    logger.info("LiveKit room connected; starting agent session.")

    await session.start(
        room=ctx.room,
        agent=Assistant(chat_ctx=initial_ctx, instructions=instructions),
        room_input_options=room_input_options,
    )

    await session.generate_reply(instructions=SESSION_INSTRUCTION)


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
