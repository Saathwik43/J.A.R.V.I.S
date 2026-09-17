"""Centralized environment configuration for J.A.R.V.I.S.

All environment variables are read and validated in one place so the rest
of the codebase never calls os.getenv() directly.
"""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("jarvis.config")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r, falling back to %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r, falling back to %s", name, raw, default)
        return default


@dataclass(frozen=True)
class Settings:
    # Google / Gemini realtime model (LiveKit room / voice)
    google_model: str
    google_voice: str
    temperature: float

    # Console text pipeline (STT → text LLM → TTS)
    llm_provider: str
    google_text_model: str
    openai_text_model: str

    # Room / audio
    use_bvc: bool
    video_enabled: bool

    # Memory (Mem0)
    mem0_user_id: str
    memory_limit: int

    # Integrations
    n8n_mcp_server_url: str | None
    gmail_user: str | None
    gmail_app_password: str | None


def _load() -> Settings:
    return Settings(
        google_model=os.getenv(
            "JARVIS_GOOGLE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
        ),
        google_voice=os.getenv("JARVIS_GOOGLE_VOICE", "Charon"),
        temperature=_env_float("JARVIS_TEMPERATURE", 0.8),
        llm_provider=(os.getenv("JARVIS_LLM_PROVIDER") or "google").strip().lower(),
        google_text_model=os.getenv("JARVIS_GOOGLE_TEXT_MODEL", "gemini-2.5-flash"),
        openai_text_model=os.getenv("JARVIS_OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        use_bvc=_env_bool("JARVIS_USE_BVC", True),
        video_enabled=_env_bool("JARVIS_VIDEO_ENABLED", True),
        # Keep prior default so existing Mem0 memories stay attached if .env omits this.
        mem0_user_id=os.getenv("MEM0_USER_ID", "Saathwik"),
        memory_limit=_env_int("JARVIS_MEMORY_LIMIT", 50),
        n8n_mcp_server_url=os.getenv("N8N_MCP_SERVER_URL") or None,
        gmail_user=os.getenv("GMAIL_USER") or None,
        gmail_app_password=os.getenv("GMAIL_APP_PASSWORD") or None,
    )


settings = _load()
