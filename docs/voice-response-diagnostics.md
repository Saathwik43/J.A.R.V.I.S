# Voice output and response-return diagnostics

This document captures the most likely failure points found in the current LiveKit/Gemini realtime assistant path and the improvements to prioritize.

## High-probability failures

1. **MCP integration keyword mismatch blocks startup**
   - `agent.py` passed `mcp_server=[mcp_server]`, but `MCPToolsIntegration.create_agent_with_tools` expects `mcp_servers`.
   - That raises a `TypeError` before `session.start(...)`, so the assistant never reaches the room/audio pipeline and no voice output can be produced.

2. **Missing `N8N_MCP_SERVER_URL` can still trigger an MCP connection attempt**
   - The previous startup path always constructed an SSE MCP server, even when the URL was unset.
   - A missing or malformed URL can delay or fail agent creation, preventing or slowing responses before LiveKit audio starts.

3. **Model or voice configuration may be invalid for the installed Google LiveKit plugin**
   - The realtime model and voice are environment-driven, but there is no validation before session startup.
   - If `JARVIS_GOOGLE_MODEL` or `JARVIS_GOOGLE_VOICE` is unsupported by the installed plugin/provider account, the session can fail at model initialization or on first generation.

4. **Initial context is injected as an assistant message**
   - Memory context is currently added with role `assistant`.
   - This can confuse the model into treating memory as prior assistant speech instead of private/system context, which can leak memory into responses or make the opening response odd.

5. **Prompt forces one-sentence responses for all tasks**
   - The persona prompt says to only answer in one sentence.
   - That can make tool results, diagnostics, email confirmations, or multi-step answers feel truncated or missing even when the model returns successfully.

6. **Blocking external tools can increase response latency**
   - Weather, web search, email, Mem0, and MCP calls depend on external services.
   - Timeouts exist for weather, but search/email/MCP startup have less explicit latency control, so tool-backed responses can appear not to return.

7. **Memory writes occur during live conversation events**
   - Every user/assistant conversation item can spawn a Mem0 write task.
   - Failures are caught, but high latency or rate limits may add event-loop pressure and noisy logs during realtime interaction.

## Improvements to prioritize

1. **Keep audio startup independent from optional integrations**
   - Skip MCP setup when `N8N_MCP_SERVER_URL` is missing.
   - Continue starting the LiveKit session even if MCP tool loading fails.

2. **Add startup configuration checks**
   - Log the selected realtime model and voice.
   - Validate required credentials and optional integration URLs before connecting.
   - Fail fast only for truly required audio/session settings.

3. **Use a clearer role for memory context**
   - Prefer a system/developer-style context mechanism if supported by the installed LiveKit SDK.
   - If not supported, explicitly label the injected content as non-user-facing context and ensure it is excluded from memory writes.

4. **Relax the one-sentence rule for tool results and diagnostics**
   - Keep the butler style for casual conversation, but allow concise multi-sentence responses when a tool result, error, or diagnostic needs clarity.

5. **Add observability around the response path**
   - Log milestones: room connect started/completed, session start started/completed, initial reply requested/completed, tool call started/completed.
   - Include elapsed times so stalls are easy to locate.

6. **Add end-to-end smoke tests where possible**
   - Unit-test import/config paths.
   - Mock MCP and Mem0 failures to verify the assistant still starts.
   - Run a LiveKit sandbox/manual test for voice input, model response, and audio output.
