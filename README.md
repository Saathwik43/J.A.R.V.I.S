# J.A.R.V.I.S

J.A.R.V.I.S is a highly capable, voice-first AI Personal Assistant inspired by the digital assistant from Iron Man. Built on top of **LiveKit** for low-latency Real-Time Communication (RTC) and powered by **Google's Gemini Realtime Native Audio Model**, J.A.R.V.I.S can maintain conversations, remember past interactions across sessions using **Mem0**, and execute real-world tasks using integrated tools and the **Model Context Protocol (MCP)**.

## Features

- 🗣️ **Real-time Voice Interaction**: Uses Google's `gemini-2.5-flash-native-audio-preview` for high-quality, ultra-low latency voice conversations.
- 🧠 **Persistent Long-Term Memory**: Integrates with [Mem0](https://github.com/mem0ai/mem0) to remember user preferences, previous conversations, and context across multiple sessions.
- 🔧 **Integrated Tools**: Given its capabilities, J.A.R.V.I.S can:
  - Check the current weather anywhere in the world (`wttr.in`).
  - Search the web using DuckDuckGo.
  - Send emails via Gmail SMTP natively.
  - Diagnose memory synchronization.
- 🔌 **Extensible via MCP**: Supports the Model Context Protocol (via an N8N MCP server) to dynamically load and utilize external tools.
- 🤫 **Noise Cancellation**: Leverages Background Voice Cancellation (BVC) for clear interactions even in noisy environments.
- 👔 **Classy Persona**: Implements a dedicated sassy, classy butler persona ("Will do, Sir!", "Roger Boss!").

## Prerequisites

- Python 3.10+
- Open-source packages (see `requirements.txt`)
- Mem0 API access
- LiveKit Server Configuration
- Google AI credentials
- Gmail App Password (for email functionality)

## Installation

1. Clone this repository (ensure you pull all modules).
2. Create and activate a Virtual Environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Duplicate, create or edit the `.env` file in the root of the project to include the following required environment variables:

```env
# Google & Gemini Models
JARVIS_GOOGLE_MODEL=gemini-2.5-flash-native-audio-preview-12-2025
JARVIS_GOOGLE_VOICE=Charon
JARVIS_TEMPERATURE=0.8

# Memory Configuration (Mem0)
MEM0_USER_ID=your_username # Used to distinguish your memories
MEM0_API_KEY=your_mem0_key

# Communication & Noise Cancellation
JARVIS_USE_BVC=true

# External Service Integrations
N8N_MCP_SERVER_URL=your_n8n_mcp_url

# Email / Gmail Setup (For send_email tool)
GMAIL_USER=your_email@gmail.com
GMAIL_APP_PASSWORD=your_app_password
```

## Running the Assistant

Start the LiveKit agent process using:

```bash
python agent.py start
```

Connect your LiveKit frontend (e.g., LiveKit Sandbox or a custom UI) to your workspace to start chatting with J.A.R.V.I.S via voice immediately.

## Project Structure

- **`agent.py`**: The core application logic establishing the LiveKit connection, defining the Assistant object, managing the session context, and bootstrapping Mem0 callbacks.
- **`tools.py`**: Contains the custom function tools injected into the Assistant (web search, weather, emails, memory debugging).
- **`prompts.py`**: Contains the system prompts shaping the persona and session instruction management.
- **`mcp_client/`**: Handles Server-Sent Events (SSE) connections to external MCPs (like N8N).

## Security Notice

Certain files such as `.env`, `keys.txt`, and the `KMS/` directory contain sensitive credentials and are strictly excluded from version control via `.gitignore`. Do not commit these files.
