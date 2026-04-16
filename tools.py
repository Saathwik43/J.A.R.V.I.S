import logging
import asyncio
import time
from livekit.agents import function_tool, RunContext
import requests
from langchain_community.tools import DuckDuckGoSearchRun
import os
import smtplib
from email.mime.multipart import MIMEMultipart  
from email.mime.text import MIMEText
from typing import Optional
from mem0 import AsyncMemoryClient

HTTP_TIMEOUT_SECONDS = 6
_WEATHER_SESSION = requests.Session()
_SEARCH_TOOL = DuckDuckGoSearchRun()


def _get_weather_sync(city: str) -> str:
    response = _WEATHER_SESSION.get(
        f"https://wttr.in/{city}?format=3",
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code == 200:
        return response.text.strip()
    raise requests.RequestException(f"Weather API returned {response.status_code}")


def _search_web_sync(query: str) -> str:
    return _SEARCH_TOOL.run(tool_input=query)

@function_tool()
async def get_weather(
    context: RunContext,  # type: ignore
    city: str) -> str:
    """
    Get the current weather for a given city.
    """
    city = city.strip()
    if not city:
        return "Please provide a city name."

    start = time.perf_counter()
    try:
        result = await asyncio.to_thread(_get_weather_sync, city)
        logging.info(
            "Weather for %s returned in %.2fs",
            city,
            time.perf_counter() - start,
        )
        return result
    except requests.Timeout:
        logging.error(f"Weather request timed out for {city}")
        return f"Weather service timed out for {city}. Please try again."
    except requests.RequestException as e:
        logging.error(f"Weather request error for {city}: {e}")
        return f"Could not retrieve weather for {city}."
    except Exception as e:
        logging.error(f"Error retrieving weather for {city}: {e}")
        return f"An error occurred while retrieving weather for {city}." 

@function_tool()
async def search_web(
    context: RunContext,  # type: ignore
    query: str) -> str:
    """
    Search the web using DuckDuckGo.
    """
    query = query.strip()
    if not query:
        return "Please provide a search query."

    start = time.perf_counter()
    try:
        results = await asyncio.to_thread(_search_web_sync, query)
        if not results or not str(results).strip():
            return f"No search results found for '{query}'."
        logging.info(
            "Search for '%s' returned in %.2fs",
            query,
            time.perf_counter() - start,
        )
        return results
    except Exception as e:
        logging.error(f"Error searching the web for '{query}': {e}")
        return f"An error occurred while searching the web for '{query}'."    

@function_tool()    
async def send_email(
    context: RunContext,  # type: ignore
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> str:
    """
    Send an email through Gmail.
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        message: Email body content
        cc_email: Optional CC email address
    """
    try:
        # Gmail SMTP configuration
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        
        # Get credentials from environment variables
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")  # Use App Password, not regular password
        
        if not gmail_user or not gmail_password:
            logging.error("Gmail credentials not found in environment variables")
            return "Email sending failed: Gmail credentials not configured."
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add CC if provided
        recipients = [to_email]
        if cc_email:
            msg['Cc'] = cc_email
            recipients.append(cc_email)
        
        # Attach message body
        msg.attach(MIMEText(message, 'plain'))
        
        # Connect to Gmail SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Enable TLS encryption
        server.login(gmail_user, gmail_password)
        
        # Send email
        text = msg.as_string()
        server.sendmail(gmail_user, recipients, text)
        server.quit()
        
        logging.info(f"Email sent successfully to {to_email}")
        return f"Email sent successfully to {to_email}"
        
    except smtplib.SMTPAuthenticationError:
        logging.error("Gmail authentication failed")
        return "Email sending failed: Authentication error. Please check your Gmail credentials."
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error occurred: {e}")
        return f"Email sending failed: SMTP error - {str(e)}"
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return f"An error occurred while sending email: {str(e)}"


@function_tool()
async def debug_memory_sync(
    context: RunContext,  # type: ignore
    contains_text: Optional[str] = None,
    max_wait_seconds: int = 10,
    poll_interval_seconds: int = 2,
) -> str:
    """
    Poll Mem0 for recently stored memories and report visibility.
    """
    user_id = os.getenv("MEM0_USER_ID", "Saathwik")
    max_wait_seconds = max(2, min(max_wait_seconds, 30))
    poll_interval_seconds = max(1, min(poll_interval_seconds, 5))
    deadline = time.monotonic() + max_wait_seconds
    contains_text_norm = (contains_text or "").strip().lower()

    try:
        mem0 = AsyncMemoryClient()
    except Exception as e:
        logging.error("Mem0 debug failed to initialize client: %s", e)
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
            logging.warning("Mem0 debug poll error on attempt %d: %s", attempts, e)

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
