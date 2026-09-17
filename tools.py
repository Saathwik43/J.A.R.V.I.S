"""Custom function tools for J.A.R.V.I.S: weather, web search, email, memory debug."""

import asyncio
import logging
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

import requests
from ddgs import DDGS
from livekit.agents import RunContext, function_tool
from mem0 import AsyncMemoryClient

from config import settings

logger = logging.getLogger("jarvis.tools")

HTTP_TIMEOUT_SECONDS = 6
SMTP_TIMEOUT_SECONDS = 15
_WEATHER_SESSION = requests.Session()
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- Weather ---------------------------------------------------------------

def _get_weather_sync(city: str) -> str:
    response = _WEATHER_SESSION.get(
        f"https://wttr.in/{city}?format=3",
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code == 200:
        return response.text.strip()
    raise requests.RequestException(f"Weather API returned {response.status_code}")


@function_tool()
async def get_weather(
    context: RunContext,  # type: ignore
    city: str,
) -> str:
    """
    Get the current weather for a given city.
    """
    city = city.strip()
    if not city:
        return "Please provide a city name."

    start = time.perf_counter()
    try:
        result = await asyncio.to_thread(_get_weather_sync, city)
        logger.info("Weather for %s returned in %.2fs", city, time.perf_counter() - start)
        return result
    except requests.Timeout:
        logger.error("Weather request timed out for %s", city)
        return f"Weather service timed out for {city}. Please try again."
    except requests.RequestException as e:
        logger.error("Weather request error for %s: %s", city, e)
        return f"Could not retrieve weather for {city}."
    except Exception as e:
        logger.error("Error retrieving weather for %s: %s", city, e)
        return f"An error occurred while retrieving weather for {city}."


# --- Web search ------------------------------------------------------------

def _search_web_sync(query: str) -> str:
    results = DDGS().text(query, max_results=5)
    lines = []
    for r in results:
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        href = (r.get("href") or "").strip()
        lines.append(f"- {title}: {body} ({href})")
    return "\n".join(lines)


@function_tool()
async def search_web(
    context: RunContext,  # type: ignore
    query: str,
) -> str:
    """
    Search the web using DuckDuckGo and return the top results.
    """
    query = query.strip()
    if not query:
        return "Please provide a search query."

    start = time.perf_counter()
    try:
        results = await asyncio.to_thread(_search_web_sync, query)
        if not results.strip():
            return f"No search results found for '{query}'."
        logger.info("Search for '%s' returned in %.2fs", query, time.perf_counter() - start)
        return results
    except Exception as e:
        logger.error("Error searching the web for '%s': %s", query, e)
        return f"An error occurred while searching the web for '{query}'."


# --- Email -----------------------------------------------------------------

def _clean_header(value: str) -> str:
    """Strip CR/LF to prevent SMTP header injection from model-generated text."""
    return value.replace("\r", " ").replace("\n", " ").strip()


def _valid_email(address: str) -> bool:
    _, addr = parseaddr(address)
    return bool(_EMAIL_RE.match(addr))


def _send_email_sync(
    gmail_user: str,
    gmail_password: str,
    to_email: str,
    subject: str,
    message: str,
    cc_email: str | None,
) -> None:
    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg["Subject"] = subject

    recipients = [to_email]
    if cc_email:
        msg["Cc"] = cc_email
        recipients.append(cc_email)

    msg.attach(MIMEText(message, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())


@function_tool()
async def send_email(
    context: RunContext,  # type: ignore
    to_email: str,
    subject: str,
    message: str,
    cc_email: str | None = None,
) -> str:
    """
    Send an email through Gmail. Only call this after the user has verbally
    confirmed the recipient address and subject.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        message: Email body content
        cc_email: Optional CC email address
    """
    if not settings.gmail_user or not settings.gmail_app_password:
        logger.error("Gmail credentials not found in environment variables")
        return "Email sending failed: Gmail credentials not configured."

    to_email = _clean_header(to_email)
    subject = _clean_header(subject)
    cc_email = _clean_header(cc_email) if cc_email else None

    if not _valid_email(to_email):
        return f"Email sending failed: '{to_email}' is not a valid email address."
    if cc_email and not _valid_email(cc_email):
        return f"Email sending failed: CC address '{cc_email}' is not a valid email address."

    try:
        await asyncio.to_thread(
            _send_email_sync,
            settings.gmail_user,
            settings.gmail_app_password,
            to_email,
            subject,
            message,
            cc_email,
        )
        logger.info("Email sent successfully to %s", to_email)
        return f"Email sent successfully to {to_email}"
    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail authentication failed")
        return "Email sending failed: Authentication error. Please check your Gmail credentials."
    except smtplib.SMTPException as e:
        logger.error("SMTP error occurred: %s", e)
        return f"Email sending failed: SMTP error - {e}"
    except Exception as e:
        logger.error("Error sending email: %s", e)
        return f"An error occurred while sending email: {e}"


# --- Memory diagnostics ----------------------------------------------------

@function_tool()
async def debug_memory_sync(
    context: RunContext,  # type: ignore
    contains_text: str | None = None,
    max_wait_seconds: int = 10,
    poll_interval_seconds: int = 2,
) -> str:
    """
    Poll Mem0 for recently stored memories and report visibility.
    """
    user_id = settings.mem0_user_id
    max_wait_seconds = max(2, min(max_wait_seconds, 30))
    poll_interval_seconds = max(1, min(poll_interval_seconds, 5))
    deadline = time.monotonic() + max_wait_seconds
    contains_text_norm = (contains_text or "").strip().lower()

    try:
        mem0 = AsyncMemoryClient()
    except Exception as e:
        logger.error("Mem0 debug failed to initialize client: %s", e)
        return f"Mem0 debug failed: could not initialize client ({e})."

    attempts = 0
    last_count = 0
    matched = []

    while time.monotonic() < deadline:
        attempts += 1
        try:
            results = await mem0.get_all(filters={"user_id": user_id})
            memories = results.get("results", []) if isinstance(results, dict) else []
            last_count = len(memories)

            if contains_text_norm:
                matched = [
                    m for m in memories
                    if contains_text_norm in str(m.get("memory", "")).lower()
                ]
                if matched:
                    break
            else:
                break
        except Exception as e:
            logger.warning("Mem0 debug poll error on attempt %d: %s", attempts, e)

        await asyncio.sleep(poll_interval_seconds)

    if contains_text_norm:
        if matched:
            latest = matched[0]
            return (
                f"Mem0 sync OK for user '{user_id}'. "
                f"Found match after {attempts} poll(s): "
                f"\"{latest.get('memory', '')}\" (updated_at={latest.get('updated_at', 'unknown')})."
            )
        return (
            f"Mem0 sync pending for user '{user_id}'. "
            f"No memory containing '{contains_text}' after {attempts} poll(s) "
            f"over {max_wait_seconds}s. Current memory count: {last_count}."
        )

    return (
        f"Mem0 reachable for user '{user_id}'. "
        f"Fetched {last_count} memories after {attempts} poll(s)."
    )
