import json
import time
import urllib.request
import urllib.error
from PyQt5.QtCore import QThread, pyqtSignal

from .config import (
    API_URL, SYSTEM_PROMPT, RETRY_COUNT, TIMEOUT_SECONDS,
    DEFAULT_MODEL, logger, log_exception
)
from .tools import execute_tool


class ConversationWorker(QThread):
    """Runs the full API request (with retries) in a background thread.
    
    Emits response_ready(dict) on success, error_occurred(str) on failure.
    Does NOT call QApplication.processEvents() or modify any Qt widgets.
    Does NOT modify the messages list.
    """
    response_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, messages, settings, tools, parent=None):
        super().__init__(parent)
        self.messages = messages
        self.settings = settings
        self.tools = tools
        self._abort_flag = False

    def abort(self):
        self._abort_flag = True

    def run(self):
        response, error = _make_api_request(self.messages, self.settings, self.tools, lambda: self._abort_flag)
        if self._abort_flag:
            return
        if error:
            self.error_occurred.emit(error)
        else:
            self.response_ready.emit(response)


def build_user_message(user_prompt, image_b64=None):
    """Build a user message dict for the conversation history.
    
    Called from the main thread before starting the worker.
    """
    content = [{"type": "text", "text": user_prompt}] if user_prompt else []
    if image_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
        })
    return {"role": "user", "content": content}


def sanitize_history(messages):
    """Strip incomplete tool-call groups from the end of message history.

    Call this before appending a new user message to history. If the previous
    conversation turn ended with an unclosed tool chain (abort, error, model
    switch), the trailing assistant(tool_calls) + tool result messages are
    removed so providers don't reject the role ordering.
    """
    if not messages:
        return
    if messages[-1].get("role") != "tool":
        return
    stripped = 0
    while messages and messages[-1].get("role") == "tool":
        messages.pop()
        stripped += 1
    if messages and messages[-1].get("role") == "assistant" and "tool_calls" in messages[-1]:
        messages.pop()
        stripped += 1
    if stripped:
        logger.info(f"Sanitized history: removed {stripped} incomplete messages")


def _make_api_request(messages, settings, tools, abort_check):
    """Make an API request to OpenRouter. Runs in worker thread.
    
    Args:
        messages: list of message dicts (user/assistant/tool)
        settings: dict with 'api_key', 'model', 'temperature'
        tools: pre-built tool schemas list (built on main thread)
        abort_check: callable returning True if aborted
    Args:
        messages: list of message dicts (user/assistant/tool)
        settings: dict with 'api_key', 'model', 'temperature'
        abort_check: callable returning True if aborted
        
    Returns:
        (response_dict | None, error_string | None)
    """
    api_key = settings.get('api_key', '')
    if not api_key:
        return None, "No API key configured. Open Settings to add your API key."

    model = settings.get('model', DEFAULT_MODEL)
    temperature = settings.get('temperature', 0.7)
    logger.info(f"[Worker] Starting API request: model={model}, temp={temperature}")

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": 4096
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "LLM Image Chat",
        "X-Title": "LLM Image Chat"
    }

    try:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST'
        )
    except Exception as e:
        log_exception(e, "_make_api_request (request build)")
        return None, f"Error building request: {str(e)}"

    for attempt in range(RETRY_COUNT):
        if abort_check():
            logger.info("[Worker] Aborted before attempt")
            return None, None

        if attempt > 0:
            logger.info(f"[Worker] Retry attempt {attempt + 1}/{RETRY_COUNT}")

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode('utf-8'))
                logger.info(f"[Worker] API response received, choices: {len(result.get('choices', []))}")
                return result, None

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            code = e.code
            logger.error(f"[Worker] HTTP Error {code}: {error_body}")

            try:
                error_data = json.loads(error_body)
                api_message = error_data.get("error", {}).get("message", error_body[:200])
            except Exception:
                api_message = error_body[:200]

            if code >= 500 or code == 429:
                if attempt < RETRY_COUNT - 1:
                    wait_time = 2 ** attempt  # 1, 2, 4 seconds
                    logger.info(f"[Worker] HTTP {code}, waiting {wait_time}s before retry {attempt + 2}/{RETRY_COUNT}...")
                    if not abort_check():
                        time.sleep(wait_time)
                    continue
                error_type = "rate limit" if code == 429 else "server error"
                return None, f"[HTTP {code}] {error_type}. {api_message} Please wait a moment and try again."

            if code == 404:
                return None, f"[HTTP 404] {api_message} Try selecting a different model in Settings."
            return None, f"[HTTP {code}] {api_message}"

        except urllib.error.URLError as e:
            reason = str(e.reason)
            logger.error(f"[Worker] URL Error: {reason}")

            if "timed out" in reason.lower() or "10060" in reason:
                if attempt < RETRY_COUNT - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"[Worker] Socket timeout, waiting {wait_time}s before retry...")
                    if not abort_check():
                        time.sleep(wait_time)
                    continue
                return None, f"Request timed out after {RETRY_COUNT} attempts ({TIMEOUT_SECONDS}s each)."

            if "10013" in reason or "permission" in reason.lower():
                return None, "Connection failed. Check your firewall or run Krita as administrator."
            return None, f"Connection failed: {reason}"

        except Exception as e:
            log_exception(e, "_make_api_request")
            return None, f"Error: {str(e)}"

    return None, f"Request timed out after {RETRY_COUNT} attempts ({TIMEOUT_SECONDS}s each)."


def truncate_messages(messages, target_len=25):
    """Truncate message history to prevent token bloat, respecting tool-call group boundaries.
    
    Modified in place. Does not truncate below the target length.
    """
    if len(messages) <= 30:
        return
    cut_index = len(messages) - target_len
    while cut_index > 0:
        msg = messages[cut_index]
        if msg.get("role") == "tool":
            cut_index -= 1
        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            cut_index -= 1
        else:
            break
    if cut_index > 0:
        del messages[:cut_index]
        logger.debug(f"Truncated message history to {len(messages)} (cut at index {cut_index})")


def process_response(response_data, messages, ui):
    """Process an LLM response, executing tool calls if present.

    Args:
        response_data: dict from API response
        messages: list (modified in place - assistant msg + tool results appended)
        ui: object with _abort_flag, set_busy(), status_label

    Returns:
        list of event dicts on success, or None if aborted
    """
    logger.debug("process_response() called")
    logger.debug(f"Response keys: {response_data.keys()}")

    if "choices" not in response_data or len(response_data["choices"]) == 0:
        logger.error(f"No choices in response: {response_data}")
        return [{"type": "error", "message": "No response from API"}]

    message = response_data["choices"][0]["message"]
    logger.debug(f"Message keys: {message.keys()}")
    logger.debug(f"Message content length: {len(message.get('content', '')) if message.get('content') else 0}")
    logger.debug(f"Has tool_calls: {'tool_calls' in message and message['tool_calls']}")

    if "tool_calls" in message and message["tool_calls"]:
        logger.debug(f"Tool calls count: {len(message['tool_calls'])}")
        for tc in message["tool_calls"]:
            logger.debug(f"Tool call: {tc['function']['name']}, args preview: {tc['function']['arguments'][:100]}...")

    history_message = {"role": "assistant", "content": message.get("content") or ""}
    if "tool_calls" in message:
        clean_tool_calls = []
        for tc in message["tool_calls"]:
            clean_tc = {k: v for k, v in tc.items() if k != "index"}
            clean_tool_calls.append(clean_tc)
        history_message["tool_calls"] = clean_tool_calls
    messages.append(history_message)

    events = []

    if message.get("content"):
        events.append({"type": "text", "content": message["content"]})

    if "tool_calls" in message and message["tool_calls"]:
        for tool_call in message["tool_calls"]:
            if ui._abort_flag:
                logger.info("Aborted before tool execution")
                return None

            tool_name = tool_call["function"]["name"]
            args_str = tool_call["function"]["arguments"]
            tool_call_id = tool_call["id"]

            logger.info(f"Executing tool: {tool_name}, id: {tool_call_id}")
            logger.debug(f"Tool arguments string: {args_str}")

            try:
                args = json.loads(args_str)
                logger.debug(f"Parsed arguments: {args}")
            except Exception as e:
                logger.warning(f"Failed to parse tool arguments as JSON: {e}")
                args = {}

            events.append({"type": "tool_start", "name": tool_name,
                           "message": f"Calling {tool_name}..."})
            ui.set_busy(f"Executing {tool_name}...")

            if ui._abort_flag:
                return None

            try:
                result = execute_tool(tool_name, args)
                logger.info(f"Tool {tool_name} result: success={result.get('success')}, message={result.get('message', result.get('error', 'no message'))}")
            except Exception as e:
                log_exception(e, f"execute_tool({tool_name})")
                result = {"success": False, "error": str(e)}

            if result.get("success"):
                msg = result.get("message", "Done")
                events.append({"type": "tool_result", "name": tool_name,
                               "success": True, "message": msg})
            else:
                events.append({"type": "tool_result", "name": tool_name,
                               "success": False, "message": result.get("error", "Unknown error")})

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result)
            })
            logger.debug(f"Added tool result to message history")

        if ui._abort_flag:
            logger.info("Aborted after tool execution, not continuing conversation")
            return None

    return events
