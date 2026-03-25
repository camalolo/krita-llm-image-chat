from krita import DockWidget
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                              QPushButton, QCheckBox, QLabel, QTextEdit,
                              QDialog)
from PyQt5.QtCore import Qt, QEvent, QTimer

from .config import DEFAULT_MODEL, TIMEOUT_SECONDS, RETRY_COUNT, SETTINGS_PATH, logger, log_exception, get_valid_model_id
from .settings_dialog import SettingsDialog
from .image_capture import get_current_image_base64
from .api_client import ConversationWorker, build_user_message, process_response, truncate_messages
import json
import os
import time
import html


class LLMChatDocker(DockWidget):
    def __init__(self):
        super().__init__()
        logger.info("=" * 60)
        logger.info("LLMChatDocker initializing...")
        self.setWindowTitle("LLM Image Chat")
        self.messages = []
        self.settings = {}
        self._abort_flag = False
        self._history = []
        self._history_index = -1
        self._draft_text = ""
        self._worker = None
        self._tool_round = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_start = 0
        self._spinner_frame = 0
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setSingleShot(True)
        self._watchdog_timer.timeout.connect(self._on_worker_timeout)
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
        self.input_edit.installEventFilter(self)
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
        self.vision_note_label = QLabel("")
        self.vision_note_label.setStyleSheet("color: #e67e22; font-style: italic; font-size: 11px;")
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_conversation)
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        options_layout.addWidget(self.include_image_cb)
        options_layout.addWidget(self.vision_note_label)
        options_layout.addStretch()
        options_layout.addWidget(self.clear_button)
        options_layout.addWidget(self.settings_button)
        layout.addLayout(options_layout)

        self.setWidget(widget)

    def eventFilter(self, obj, event):
        if obj is self.input_edit and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                if self._history:
                    if self._history_index == -1:
                        self._draft_text = self.input_edit.text()
                    self._history_index = min(self._history_index + 1, len(self._history) - 1)
                    self.input_edit.setText(self._history[self._history_index])
                return True
            elif key == Qt.Key_Down:
                if self._history_index >= 0:
                    self._history_index -= 1
                    if self._history_index == -1:
                        self.input_edit.setText(self._draft_text)
                    else:
                        self.input_edit.setText(self._history[self._history_index])
                return True
            elif key == Qt.Key_Escape:
                self.input_edit.clear()
                self._history_index = -1
                return True
        return super().eventFilter(obj, event)

    def load_settings(self):
        logger.debug("LLMChatDocker.load_settings() called")
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r') as f:
                    self.settings = json.load(f)
                self.settings['model'] = get_valid_model_id(self.settings.get('model', DEFAULT_MODEL))
                logger.info(f"Settings loaded: model={self.settings.get('model')}, temp={self.settings.get('temperature')}")
                self._update_vision_ui()
            else:
                self.settings = {'api_key': '', 'model': DEFAULT_MODEL, 'temperature': 0.7}
                logger.debug("No settings file, using defaults")
                self._update_vision_ui()
        except Exception as e:
            log_exception(e, "LLMChatDocker.load_settings")
            self.settings = {'api_key': '', 'model': DEFAULT_MODEL, 'temperature': 0.7}
            self._update_vision_ui()

    def open_settings(self):
        logger.debug("Opening settings dialog")
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.settings = dialog.get_settings()
            logger.info("Settings updated from dialog")
            self.add_message("System", "Settings saved successfully.")
            self._update_vision_ui()
        else:
            logger.debug("Settings dialog cancelled")

    def clear_conversation(self):
        logger.info("Clearing conversation history")
        self._watchdog_timer.stop()
        self.messages = []
        self._history = []
        self._history_index = -1
        self._draft_text = ""
        self._tool_round = 0
        self._spinner_frame = 0
        self.chat_history.clear()
        self.add_message("System", "Conversation cleared.")

    def _update_vision_ui(self):
        from .config import model_supports_vision
        model_id = self.settings.get('model', DEFAULT_MODEL)
        has_vision = model_supports_vision(model_id)
        if has_vision:
            self.include_image_cb.setEnabled(True)
            self.vision_note_label.setText("")
        else:
            self.include_image_cb.setChecked(False)
            self.include_image_cb.setEnabled(False)
            self.vision_note_label.setText("(No vision)")

    def set_busy(self, message="Thinking..."):
        self._abort_flag = False
        self.status_label.setText(message)
        self.send_button.hide()
        self.abort_button.show()
        self.input_edit.setEnabled(False)
        self.include_image_cb.setEnabled(False)
        self.clear_button.setEnabled(False)

    def set_ready(self):
        self.status_label.setText("")
        self.send_button.show()
        self.abort_button.hide()
        self.input_edit.setEnabled(True)
        self._update_vision_ui()
        self.clear_button.setEnabled(True)

    def abort(self):
        logger.info("Abort requested by user")
        self._abort_flag = True
        self._countdown_timer.stop()
        self._watchdog_timer.stop()

        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(5000)
            if self._worker.isRunning():
                logger.warning("Worker did not exit cleanly after abort, terminating as last resort")
                self._worker.terminate()
                self._worker.wait(2000)
            logger.info("Worker thread stopped")

        self._worker = None
        self.set_ready()
        self.add_message("System", "⚠ Aborted by user.")

    def send_message(self):
        user_input = self.input_edit.text().strip()
        if not user_input:
            logger.debug("send_message called with empty input, ignoring")
            return

        if self._worker is not None:
            logger.debug("send_message called while busy, ignoring")
            return

        logger.info(f"User message: {user_input[:100]}{'...' if len(user_input) > 100 else ''}")

        self.input_edit.clear()
        self._history.insert(0, user_input)
        self._history_index = -1
        self._draft_text = ""
        self.add_message("You", user_input)
        self.set_busy("Thinking...")

        image_b64 = None
        if self.include_image_cb.isChecked():
            logger.debug("Include image checkbox is checked, capturing image...")
            self.set_busy("Capturing image...")
            image_b64 = get_current_image_base64()
            if not image_b64:
                logger.warning("Image capture failed, proceeding without image")
                self.add_message("Warning", "Could not capture image. Proceeding without image.")
        else:
            logger.debug("Include image checkbox is not checked")

        if self._abort_flag:
            logger.info("Aborted during image capture phase")
            self.set_ready()
            return

        self.messages.append(build_user_message(user_input, image_b64))
        self._tool_round = 0
        self._spinner_frame = 0
        self._start_api_call()

    def _start_api_call(self):
        if self._tool_round > 0:
            self.set_busy(f"Step {self._tool_round}...")
        else:
            self.set_busy("Waiting for LLM response...")

        self._worker = ConversationWorker(self.messages, self.settings, parent=self)
        self._worker.response_ready.connect(self._on_response)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

        self._countdown_start = time.time()
        self._countdown_timer.start(1000)

        max_wait = TIMEOUT_SECONDS * RETRY_COUNT + 15
        self._watchdog_timer.start(max_wait * 1000)

    def _update_countdown(self):
        elapsed = time.time() - self._countdown_start
        frames = ["●○○", "○●○", "○○●"]
        self._spinner_frame = (self._spinner_frame + 1) % len(frames)
        spinner = frames[self._spinner_frame]
        if self._tool_round > 0:
            self.status_label.setText(f"{spinner} Step {self._tool_round} ({elapsed:.0f}s)...")
        else:
            self.status_label.setText(f"{spinner} Waiting for LLM response... ({elapsed:.0f}s)")

    def _on_response(self, response):
        self._countdown_timer.stop()
        self._watchdog_timer.stop()

        if self._abort_flag:
            self._worker = None
            return

        self._worker = None

        try:
            events = process_response(response, self.messages, self)
        except Exception as e:
            log_exception(e, "_on_response")
            self.set_ready()
            self.add_message("Error", f"Error processing response: {str(e)}")
            return

        if events is None:
            self.set_ready()
            return

        for event in events:
            etype = event["type"]
            if etype == "text":
                self.add_message("LLM", event["content"])
            elif etype == "tool_start":
                self.add_message("Tool", event["message"])
            elif etype == "tool_result":
                name = event["name"]
                if event["success"]:
                    self.add_message("System", f"✓ {name}: {event['message']}")
                else:
                    self.add_message("Error", f"✗ {name}: {event['message']}")
            elif etype == "error":
                self.add_message("Error", event["message"])

        has_tool_calls = any(e["type"] in ("tool_start", "tool_result") for e in events)
        if has_tool_calls:
            self._tool_round += 1
            MAX_TOOL_ROUNDS = 30
            if self._tool_round >= MAX_TOOL_ROUNDS:
                self.add_message("System", f"⚠ Stopped after {MAX_TOOL_ROUNDS} tool calls. Please try a simpler request or clear the conversation.")
                self.set_ready()
                return
            truncate_messages(self.messages)
            if self._abort_flag:
                self.set_ready()
                return
            self.set_busy(f"Step {self._tool_round}...")
            self._start_api_call()
        else:
            self._tool_round = 0
            self.set_ready()

    def _on_error(self, error_msg):
        self._countdown_timer.stop()
        self._watchdog_timer.stop()

        if self._abort_flag:
            self._worker = None
            return

        self._worker = None
        self.set_ready()
        self.add_message("Error", error_msg)

    def _on_worker_timeout(self):
        self._countdown_timer.stop()
        logger.error("Worker thread watchdog triggered — worker appears dead")
        if self._worker and self._worker.isRunning():
            self._abort_flag = True
            self._worker.abort()
            self._worker.wait(2000)
            if self._worker.isRunning():
                self._worker.terminate()
                self._worker.wait(2000)
        self._worker = None
        self.set_ready()
        self.add_message("Error", "Request timed out. The API may be temporarily unavailable.")

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

        escaped_text = html.escape(str(text))
        formatted = f'<p><span style="color:{color}; font-weight:bold;">{sender}:</span> {escaped_text}</p>'
        self.chat_history.append(formatted)

        scrollbar = self.chat_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def canvasChanged(self, canvas):
        pass
