from krita import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QImage
import urllib.request
import urllib.error
import json
import base64
import os
import logging
import traceback
from datetime import datetime
from .tools import generate_tools, execute_tool

LOG_PATH = "C:/Users/camal/AppData/Roaming/krita/pykrita/llm_image_chat/llm_image_chat.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def log_exception(e, context=""):
    logger.error(f"EXCEPTION in {context}: {type(e).__name__}: {str(e)}")
    logger.debug(traceback.format_exc())

SETTINGS_PATH = "C:/Users/camal/AppData/Roaming/krita/pykrita/llm_image_chat/settings.json"

MODELS = [
    "openrouter/free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "openai/gpt-4o",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free"
]

SYSTEM_PROMPT = """You are a Krita image manipulation assistant with access to tools.

CAPABILITIES:
- Analyze images and modify them using provided tools
- Access to filters, layers, selections, document operations, colors, and fills

TOOL USAGE:
- You MUST use the tool_calls API to call tools. Never output tool calls as text.
- Simply call tools naturally in your response — the API handles the formatting.
- Call image_info first to understand the current document state.
- You may call multiple tools sequentially. Results are fed back to you.
- If a tool fails, try alternative approaches.

WORKFLOW:
1. First call image_info to understand the document
2. Plan your approach based on the user's request
3. Call tools sequentially, checking results
4. Summarize what you did for the user

Respond naturally. Use tools when you need to modify the image or gather information."""


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM Image Chat Settings")
        self.setMinimumWidth(400)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter your OpenRouter API key")
        form_layout.addRow("API Key:", self.api_key_edit)

        self.model_combo = QComboBox()
        self.model_combo.addItems(MODELS)
        form_layout.addRow("Model:", self.model_combo)

        self.temperature_slider = QSlider(Qt.Horizontal)
        self.temperature_slider.setRange(0, 20)
        self.temperature_slider.setValue(7)
        self.temperature_label = QLabel("0.7")
        self.temperature_slider.valueChanged.connect(self._update_temp_label)
        temp_layout = QHBoxLayout()
        temp_layout.addWidget(self.temperature_slider)
        temp_layout.addWidget(self.temperature_label)
        form_layout.addRow("Temperature:", temp_layout)

        layout.addLayout(form_layout)

        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_and_accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

    def _update_temp_label(self, value):
        self.temperature_label.setText(f"{value / 10:.1f}")

    def load_settings(self):
        logger.debug(f"SettingsDialog.load_settings() called, path: {SETTINGS_PATH}")
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r') as f:
                    settings = json.load(f)
                logger.debug(f"Loaded settings: model={settings.get('model')}, temp={settings.get('temperature')}, api_key={'*' * 8 if settings.get('api_key') else 'empty'}")
                self.api_key_edit.setText(settings.get('api_key', ''))
                model = settings.get('model', 'openrouter/free')
                index = self.model_combo.findText(model)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
                temp = int(settings.get('temperature', 0.7) * 10)
                self.temperature_slider.setValue(temp)
                logger.info("Settings loaded successfully")
            else:
                logger.debug("No settings file found, using defaults")
        except Exception as e:
            log_exception(e, "SettingsDialog.load_settings")

    def save_settings(self):
        logger.debug("SettingsDialog.save_settings() called")
        settings = {
            'api_key': self.api_key_edit.text(),
            'model': self.model_combo.currentText(),
            'temperature': self.temperature_slider.value() / 10
        }
        logger.debug(f"Saving settings: model={settings['model']}, temp={settings['temperature']}")
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f)
        logger.info("Settings saved successfully")

    def save_and_accept(self):
        self.save_settings()
        self.accept()

    def get_settings(self):
        return {
            'api_key': self.api_key_edit.text(),
            'model': self.model_combo.currentText(),
            'temperature': self.temperature_slider.value() / 10
        }


class RequestThread(QThread):
    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self.result = None
        self.error = None
        self.exception = None

    def run(self):
        try:
            with urllib.request.urlopen(self.request, timeout=120) as response:
                self.result = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            self.error = {"type": "http", "code": e.code, "body": error_body}
        except urllib.error.URLError as e:
            self.error = {"type": "url", "reason": str(e.reason)}
        except Exception as e:
            self.error = {"type": "exception", "message": str(e), "traceback": traceback.format_exc()}


class LLMChatDocker(DockWidget):
    def __init__(self):
        super().__init__()
        logger.info("=" * 60)
        logger.info("LLMChatDocker initializing...")
        self.setWindowTitle("LLM Image Chat")
        self.messages = []
        self.settings = {}
        self._abort_flag = False
        self._request_thread = None
        self.setup_ui()
        self.load_settings()
        logger.info("LLMChatDocker initialized successfully")

    def setup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setAcceptRichText(True)
        layout.addWidget(self.chat_history)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        layout.addWidget(self.status_label)

        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Type your message...")
        self.input_edit.returnPressed.connect(self.send_message)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        self.abort_button = QPushButton("Abort")
        self.abort_button.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold;")
        self.abort_button.clicked.connect(self.abort)
        self.abort_button.hide()
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.send_button)
        input_layout.addWidget(self.abort_button)
        layout.addLayout(input_layout)

        options_layout = QHBoxLayout()
        self.include_image_cb = QCheckBox("Include image")
        self.include_image_cb.setChecked(True)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_conversation)
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        options_layout.addWidget(self.include_image_cb)
        options_layout.addStretch()
        options_layout.addWidget(self.clear_button)
        options_layout.addWidget(self.settings_button)
        layout.addLayout(options_layout)

        self.setWidget(widget)

    def load_settings(self):
        logger.debug("LLMChatDocker.load_settings() called")
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r') as f:
                    self.settings = json.load(f)
                logger.info(f"Settings loaded: model={self.settings.get('model')}, temp={self.settings.get('temperature')}")
            else:
                self.settings = {'api_key': '', 'model': 'openrouter/free', 'temperature': 0.7}
                logger.debug("No settings file, using defaults")
        except Exception as e:
            log_exception(e, "LLMChatDocker.load_settings")
            self.settings = {'api_key': '', 'model': 'openrouter/free', 'temperature': 0.7}

    def open_settings(self):
        logger.debug("Opening settings dialog")
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.settings = dialog.get_settings()
            logger.info("Settings updated from dialog")
            self.add_message("System", "Settings saved successfully.")
        else:
            logger.debug("Settings dialog cancelled")

    def clear_conversation(self):
        logger.info("Clearing conversation history")
        self.messages = []
        self.chat_history.clear()
        self.add_message("System", "Conversation cleared.")

    def set_busy(self, message="Thinking..."):
        self._abort_flag = False
        self.status_label.setText(message)
        self.send_button.hide()
        self.abort_button.show()
        self.input_edit.setEnabled(False)
        self.include_image_cb.setEnabled(False)
        self.clear_button.setEnabled(False)
        QApplication.processEvents()

    def set_ready(self):
        self.status_label.setText("")
        self.send_button.show()
        self.abort_button.hide()
        self.input_edit.setEnabled(True)
        self.include_image_cb.setEnabled(True)
        self.clear_button.setEnabled(True)

    def abort(self):
        logger.info("Abort requested by user")
        self._abort_flag = True
        self.status_label.setText("Aborting...")
        QApplication.processEvents()
        if self._request_thread and self._request_thread.isRunning():
            self._request_thread.terminate()
            self._request_thread.wait(3000)
            logger.info("Request thread terminated")
        self.set_ready()
        self.add_message("System", "⚠ Aborted by user.")

    def get_current_image_base64(self):
        logger.debug("get_current_image_base64() called")
        doc = Krita.instance().activeDocument()
        if not doc:
            logger.warning("No active document found")
            return None
        
        node = doc.activeNode()
        if not node:
            logger.warning("No active node found")
            return None
        
        w = doc.width()
        h = doc.height()
        logger.debug(f"Document size: {w}x{h}, active node: {node.name()}")
        
        try:
            pixel_data = node.pixelData(0, 0, w, h)
            logger.debug(f"Got pixel data, length: {len(pixel_data) if pixel_data else 'None'}")
            
            qimage = QImage(pixel_data, w, h, QImage.Format_ARGB32)
            qimage = qimage.rgbSwapped()
            
            max_size = 1024
            if w > max_size or h > max_size:
                qimage = qimage.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logger.debug(f"Resized image to {qimage.width()}x{qimage.height()}")
            
            from PyQt5.QtCore import QBuffer, QByteArray
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QBuffer.WriteOnly)
            qimage.save(buffer, "JPEG", 85)
            buffer.close()
            
            b64_data = base64.b64encode(byte_array.data()).decode('utf-8')
            logger.info(f"Image captured successfully (JPEG q85), base64 length: {len(b64_data)}")
            return b64_data
        except Exception as e:
            log_exception(e, "get_current_image_base64")
            return None

    def call_llm(self, user_prompt, image_b64=None):
        logger.debug(f"call_llm() called, prompt length: {len(user_prompt) if user_prompt else 0}, has_image: {image_b64 is not None}")
        
        api_key = self.settings.get('api_key', '')
        if not api_key:
            logger.error("No API key configured")
            return None, "No API key configured. Open Settings to add your API key."
        
        model = self.settings.get('model', 'openrouter/free')
        temperature = self.settings.get('temperature', 0.7)
        logger.debug(f"Using model: {model}, temperature: {temperature}")
        
        content = [{"type": "text", "text": user_prompt}] if user_prompt else []
        if image_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
            })
            logger.debug(f"Added image to content, base64 length: {len(image_b64)}")
        
        if user_prompt:
            self.messages.append({"role": "user", "content": content})
            logger.debug(f"Added user message to history, total messages: {len(self.messages)}")
        
        tools = generate_tools()
        logger.debug(f"Generated {len(tools)} tools")
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT}
            ] + self.messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": 4096
        }
        
        logger.debug(f"Payload size: {len(json.dumps(payload))} bytes")
        logger.debug(f"Messages count in payload: {len(payload['messages'])}")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "LLM Image Chat",
            "X-Title": "LLM Image Chat"
        }
        
        logger.debug(f"Request headers set (Authorization: Bearer ***{api_key[-4:] if len(api_key) > 4 else '****'})")
        
        try:
            logger.info(f"Sending API request to OpenRouter, model: {model}")
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            
            # Run request in a thread so abort button stays responsive
            thread = RequestThread(req, self)
            self._request_thread = thread
            thread.start()
            
            # Wait loop with processEvents so UI stays responsive
            while thread.isRunning():
                QApplication.processEvents()
                if self._abort_flag:
                    thread.terminate()
                    thread.wait(3000)
                    self._request_thread = None
                    logger.info("API request aborted by user")
                    return None, "Request aborted."
                thread.msleep(50)
            
            self._request_thread = None
            
            # Check abort after thread finished
            if self._abort_flag:
                return None, "Request aborted."
            
            # Check for errors from the thread
            if thread.error is not None:
                err = thread.error
                logger.error(f"Thread error: {err}")
                
                if err["type"] == "http":
                    error_body = err["body"]
                    code = err["code"]
                    logger.error(f"HTTP Error {code}: {error_body}")
                    
                    try:
                        error_data = json.loads(error_body)
                        api_message = error_data.get("error", {}).get("message", error_body[:200])
                    except:
                        api_message = error_body[:200]
                    
                    if code == 404:
                        return None, f"[HTTP 404] {api_message} Try selecting \"nvidia/nemotron-nano-12b-v2-vl:free\" in Settings."
                    elif code >= 500:
                        return None, f"[HTTP {code}] Server error. {api_message}"
                    else:
                        return None, f"[HTTP {code}] {api_message}"
                
                elif err["type"] == "url":
                    error_reason = err["reason"]
                    logger.error(f"URL Error: {error_reason}")
                    
                    if "10013" in error_reason or "permission" in error_reason.lower():
                        return None, "Connection failed. Check your firewall or run Krita as administrator."
                    elif "timed out" in error_reason.lower() or "timeout" in error_reason.lower():
                        return None, "Connection timed out. Please try again."
                    else:
                        return None, f"Connection failed: {error_reason}"
                
                else:
                    return None, f"Error: {err.get('message', str(err))}"
            
            if thread.result:
                result = thread.result
                logger.info(f"API response received, choices: {len(result.get('choices', []))}")
                if 'error' in result:
                    logger.error(f"API returned error: {result['error']}")
                else:
                    logger.debug(f"Response has content: {'content' in result.get('choices', [{}])[0].get('message', {})}")
                    logger.debug(f"Response has tool_calls: {'tool_calls' in result.get('choices', [{}])[0].get('message', {})}")
                return result, None
            
            return None, "No response from API."
                
        except Exception as e:
            log_exception(e, "call_llm")
            self._request_thread = None
            return None, f"Error: {str(e)}"

    def process_response(self, response_data):
        logger.debug("process_response() called")
        logger.debug(f"Response keys: {response_data.keys()}")
        
        if "choices" not in response_data or len(response_data["choices"]) == 0:
            logger.error(f"No choices in response: {response_data}")
            self.add_message("Error", "No response from API")
            return
        
        message = response_data["choices"][0]["message"]
        logger.debug(f"Message keys: {message.keys()}")
        logger.debug(f"Message content length: {len(message.get('content', '')) if message.get('content') else 0}")
        logger.debug(f"Has tool_calls: {'tool_calls' in message and message['tool_calls']}")
        
        if "tool_calls" in message and message["tool_calls"]:
            logger.debug(f"Tool calls count: {len(message['tool_calls'])}")
            for tc in message["tool_calls"]:
                logger.debug(f"Tool call: {tc['function']['name']}, args preview: {tc['function']['arguments'][:100]}...")
        
        history_message = {"role": "assistant", "content": message.get("content")}
        self.messages.append(history_message)
        
        if message.get("content"):
            self.add_message("LLM", message["content"])
        
        if "tool_calls" in message and message["tool_calls"]:
            for tool_call in message["tool_calls"]:
                # Check abort before each tool call
                if self._abort_flag:
                    logger.info("Aborted before tool execution")
                    return
                
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
                
                self.add_message("Tool", f"Calling {tool_name}...")
                self.set_busy(f"Executing {tool_name}...")
                
                # Double-check abort after set_busy (which calls processEvents)
                if self._abort_flag:
                    return
                
                try:
                    result = execute_tool(tool_name, args)
                    logger.info(f"Tool {tool_name} result: success={result.get('success')}, message={result.get('message', result.get('error', 'no message'))}")
                except Exception as e:
                    log_exception(e, f"execute_tool({tool_name})")
                    result = {"success": False, "error": str(e)}
                
                if result.get("success"):
                    msg = result.get("message", "Done")
                    self.add_message("System", f"✓ {tool_name}: {msg}")
                else:
                    self.add_message("Error", f"✗ {tool_name}: {result.get('error', 'Unknown error')}")
                
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(result)
                })
                logger.debug(f"Added tool result to message history")
            
            # Check abort before continuing conversation
            if self._abort_flag:
                logger.info("Aborted after tool execution, not continuing conversation")
                return
            
            self.continue_conversation()

    def continue_conversation(self):
        logger.debug(f"continue_conversation() called, message count: {len(self.messages)}")
        
        if self._abort_flag:
            logger.info("Aborted, not continuing conversation")
            self.set_ready()
            return
        
        if len(self.messages) > 30:
            logger.debug(f"Truncating message history from {len(self.messages)} to 25")
            self.messages = self.messages[-25:]
        
        self.set_busy("Waiting for LLM response...")
        logger.debug("Calling LLM with empty prompt to continue tool execution...")
        response, error = self.call_llm("", None)
        
        if self._abort_flag:
            logger.info("Aborted during continue_conversation LLM call")
            return
        
        if error:
            logger.error(f"Error in continue_conversation: {error}")
            self.set_ready()
            self.add_message("Error", error)
            return
        
        if response:
            logger.debug("Processing continued response")
            self.process_response(response)
        self.set_ready()

    def send_message(self):
        user_input = self.input_edit.text().strip()
        if not user_input:
            logger.debug("send_message called with empty input, ignoring")
            return
        
        logger.info(f"User message: {user_input[:100]}{'...' if len(user_input) > 100 else ''}")
        
        self.input_edit.clear()
        self.add_message("You", user_input)
        self.set_busy("Thinking...")
        
        image_b64 = None
        if self.include_image_cb.isChecked():
            logger.debug("Include image checkbox is checked, capturing image...")
            self.set_busy("Capturing image...")
            image_b64 = self.get_current_image_base64()
            if not image_b64:
                logger.warning("Image capture failed, proceeding without image")
                self.add_message("Warning", "Could not capture image. Proceeding without image.")
        else:
            logger.debug("Include image checkbox is not checked")
        
        if self._abort_flag:
            logger.info("Aborted during image capture phase")
            self.set_ready()
            return
        
        self.set_busy("Waiting for LLM response...")
        logger.debug("Calling LLM API...")
        response, error = self.call_llm(user_input, image_b64)
        
        if self._abort_flag:
            logger.info("Aborted during LLM call")
            return
        
        if error:
            logger.error(f"API call failed: {error}")
            self.set_ready()
            self.add_message("Error", error)
            return
        
        if response:
            logger.debug("Processing API response")
            self.process_response(response)
        self.set_ready()

    def add_message(self, sender, text):
        logger.debug(f"UI Message [{sender}]: {text[:100]}{'...' if len(text) > 100 else ''}")
        colors = {
            "You": "#3498db",
            "LLM": "#27ae60",
            "Error": "#e74c3c",
            "System": "#7f8c8d",
            "Tool": "#9b59b6",
            "Warning": "#f39c12"
        }
        color = colors.get(sender, "#000000")
        
        formatted = f'<p><span style="color:{color}; font-weight:bold;">{sender}:</span> {text}</p>'
        self.chat_history.append(formatted)
        
        scrollbar = self.chat_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def canvasChanged(self, canvas):
        pass
