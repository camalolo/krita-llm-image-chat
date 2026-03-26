import json
import os
import urllib.request
import urllib.error

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QCheckBox, QLineEdit, QComboBox, QSlider, QLabel, QPushButton, QWidget
)
from PyQt5.QtCore import Qt

from .config import SETTINGS_PATH, MODELS, DEFAULT_MODEL, OPENAI_DEFAULT_ENDPOINT, PROVIDERS, logger, log_exception, guess_model_has_vision


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM Image Chat Settings")
        self.setMinimumWidth(420)
        self._provider_configs = {}
        self._loading = False
        self._oai_vision_override = False
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Provider selector ---
        form_layout = QFormLayout()
        self.provider_combo = QComboBox()
        for pid, display_name in PROVIDERS:
            self.provider_combo.addItem(display_name, pid)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form_layout.addRow("Provider:", self.provider_combo)

        # --- OpenRouter fields (container widget) ---
        self.or_container = QWidget()
        or_layout = QVBoxLayout(self.or_container)
        or_layout.setContentsMargins(0, 0, 0, 0)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Enter your OpenRouter API key")
        or_layout.addWidget(QLabel("API Key:"))
        or_layout.addWidget(self.api_key_edit)

        self.model_combo = QComboBox()
        for model_id, _ in MODELS:
            self.model_combo.addItem(model_id)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.model_note_label = QLabel("")
        self.model_note_label.setStyleSheet("color: #e67e22; font-style: italic; font-size: 11px;")
        or_layout.addWidget(QLabel("Model:"))
        or_layout.addWidget(self.model_combo)
        or_layout.addWidget(self.model_note_label)

        # --- OpenAI-Compatible fields (container widget) ---
        self.oai_container = QWidget()
        oai_layout = QVBoxLayout(self.oai_container)
        oai_layout.setContentsMargins(0, 0, 0, 0)

        self.oai_api_key_edit = QLineEdit()
        self.oai_api_key_edit.setEchoMode(QLineEdit.Password)
        self.oai_api_key_edit.setPlaceholderText("Optional — leave empty for local models")
        oai_layout.addWidget(QLabel("API Key:"))
        oai_layout.addWidget(self.oai_api_key_edit)

        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setPlaceholderText("http://localhost:11434/v1")
        oai_layout.addWidget(QLabel("Endpoint:"))
        oai_layout.addWidget(self.endpoint_edit)

        fetch_layout = QHBoxLayout()
        self.fetch_models_btn = QPushButton("Fetch Models")
        self.fetch_models_btn.clicked.connect(self._fetch_models)
        self.fetch_status_label = QLabel("")
        self.fetch_status_label.setStyleSheet("color: #e67e22; font-style: italic; font-size: 11px;")
        fetch_layout.addWidget(self.fetch_models_btn)
        fetch_layout.addWidget(self.fetch_status_label)
        fetch_layout.addStretch()
        oai_layout.addLayout(fetch_layout)

        self.oai_model_combo = QComboBox()
        self.oai_model_combo.setEditable(True)
        self.oai_model_combo.setPlaceholderText("Enter model name or fetch from endpoint")
        self.oai_model_combo.currentTextChanged.connect(self._on_oai_model_changed)
        oai_layout.addWidget(QLabel("Model:"))
        oai_layout.addWidget(self.oai_model_combo)

        self.oai_vision_cb = QCheckBox("Model supports vision")
        self.oai_vision_cb.setToolTip("Auto-detected from model name on fetch. Override if needed.")
        self.oai_vision_cb.toggled.connect(self._on_oai_vision_toggled)
        oai_layout.addWidget(self.oai_vision_cb)

        # Add provider containers to form
        form_layout.addRow(self.or_container)
        form_layout.addRow(self.oai_container)

        # --- Shared: Temperature ---
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

        # --- Buttons ---
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_and_accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        # Initially hide openai container
        self.oai_container.hide()

    def _update_temp_label(self, value):
        self.temperature_label.setText(f"{value / 10:.1f}")

    def _on_provider_changed(self, index):
        """Save current provider's fields, then show/hide the right container."""
        if not self._loading:
            self._save_current_provider_fields()

        pid = self.provider_combo.currentData()
        if pid == "openrouter":
            self.or_container.show()
            self.oai_container.hide()
            self._on_model_changed(self.model_combo.currentIndex())
        elif pid == "openai_compatible":
            self.or_container.hide()
            self.oai_container.show()
            self.model_note_label.setText("")

        self._load_provider_fields(pid)

    def _on_model_changed(self, index):
        if 0 <= index < len(MODELS):
            _, has_vision = MODELS[index]
            if not has_vision:
                self.model_note_label.setText("⚠ This model does not support vision — image will not be sent.")
            else:
                self.model_note_label.setText("✓ Supports vision and tools")
        else:
            self.model_note_label.setText("")

    def _on_oai_model_changed(self, model_id):
        if model_id and not self._oai_vision_override:
            self.oai_vision_cb.setChecked(guess_model_has_vision(model_id))

    def _on_oai_vision_toggled(self, checked):
        self._oai_vision_override = True

    def _save_current_provider_fields(self):
        """Save the currently visible provider's UI values into _provider_configs."""
        pid = self.provider_combo.currentData()
        if pid == "openrouter":
            self._provider_configs.setdefault("openrouter", {})
            self._provider_configs["openrouter"]["api_key"] = self.api_key_edit.text()
            self._provider_configs["openrouter"]["model"] = self.model_combo.currentText()
        elif pid == "openai_compatible":
            self._provider_configs.setdefault("openai_compatible", {})
            self._provider_configs["openai_compatible"]["api_key"] = self.oai_api_key_edit.text()
            self._provider_configs["openai_compatible"]["endpoint"] = self.endpoint_edit.text()
            self._provider_configs["openai_compatible"]["model"] = self.oai_model_combo.currentText()
            self._provider_configs["openai_compatible"]["has_vision"] = self.oai_vision_cb.isChecked()

    def _load_provider_fields(self, pid):
        """Load a provider's saved values from _provider_configs into UI fields."""
        cfg = self._provider_configs.get(pid, {})
        if pid == "openrouter":
            self.api_key_edit.setText(cfg.get("api_key", ""))
            model = cfg.get("model", DEFAULT_MODEL)
            index = self.model_combo.findText(model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
            else:
                self.model_combo.setCurrentIndex(0)
            self._on_model_changed(self.model_combo.currentIndex())
        elif pid == "openai_compatible":
            self.oai_api_key_edit.setText(cfg.get("api_key", ""))
            self.endpoint_edit.setText(cfg.get("endpoint", OPENAI_DEFAULT_ENDPOINT))
            model = cfg.get("model", "")
            self.oai_model_combo.setCurrentText(model)
            self.fetch_status_label.setText("")
            self._oai_vision_override = True
            if "has_vision" in cfg:
                self.oai_vision_cb.setChecked(cfg["has_vision"])
            else:
                self.oai_vision_cb.setChecked(guess_model_has_vision(model) if model else False)
                self._oai_vision_override = False

    def _fetch_models(self):
        """Fetch available models from the OpenAI-compatible /models endpoint."""
        self._save_current_provider_fields()
        endpoint = self.endpoint_edit.text().strip()
        if not endpoint:
            self.fetch_status_label.setText("⚠ Enter an endpoint first.")
            return

        endpoint = endpoint.rstrip('/')
        url = f"{endpoint}/models"
        self.fetch_status_label.setText("Fetching...")
        self.fetch_models_btn.setEnabled(False)

        try:
            headers = {}
            api_key = self.oai_api_key_edit.text().strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))

            models = result.get("data", [])
            if not models:
                self.fetch_status_label.setText("⚠ No models found at endpoint.")
                return

            self.oai_model_combo.blockSignals(True)
            self.oai_model_combo.clear()
            for m in models:
                model_id = m.get("id", "")
                if model_id:
                    self.oai_model_combo.addItem(model_id)
            self.oai_model_combo.blockSignals(False)

            self._oai_vision_override = False

            # Restore previously selected model if it exists
            saved_model = self._provider_configs.get("openai_compatible", {}).get("model", "")
            idx = self.oai_model_combo.findText(saved_model) if saved_model else -1
            if idx >= 0:
                self.oai_model_combo.setCurrentIndex(idx)
            else:
                self.oai_model_combo.setCurrentIndex(0)

            self.fetch_status_label.setText(f"✓ Found {len(models)} model(s)")

        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8') if e.fp else str(e)
            self.fetch_status_label.setText(f"⚠ HTTP {e.code}")
            logger.warning(f"Fetch models HTTP error: {e.code} — {body[:200]}")
        except urllib.error.URLError as e:
            self.fetch_status_label.setText("⚠ Cannot reach endpoint")
            logger.warning(f"Fetch models URL error: {e.reason}")
        except Exception as e:
            self.fetch_status_label.setText(f"⚠ Error: {str(e)[:50]}")
            log_exception(e, "_fetch_models")
        finally:
            self.fetch_models_btn.setEnabled(True)

    def load_settings(self):
        logger.debug(f"SettingsDialog.load_settings() called, path: {SETTINGS_PATH}")
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r') as f:
                    settings = json.load(f)

                provider = settings.get('provider', 'openrouter')
                self._provider_configs = settings.get('providers', {})

                # Set provider combo (block signal to prevent _on_provider_changed
                # from saving empty UI defaults over the just-loaded values)
                self._loading = True
                for i in range(self.provider_combo.count()):
                    if self.provider_combo.itemData(i) == provider:
                        self.provider_combo.setCurrentIndex(i)
                        break
                self._loading = False

                # Load temperature (shared)
                temp = int(settings.get('temperature', 0.7) * 10)
                self.temperature_slider.setValue(temp)

                # Load the active provider's fields into UI
                self._load_provider_fields(provider)

                logger.info(f"Settings loaded: provider={provider}")
            else:
                logger.debug("No settings file found, using defaults")
                self._provider_configs = {}
                self._load_provider_fields("openrouter")
        except Exception as e:
            log_exception(e, "SettingsDialog.load_settings")
            self._provider_configs = {}
            self._load_provider_fields("openrouter")

    def save_settings(self):
        logger.debug("SettingsDialog.save_settings() called")
        self._save_current_provider_fields()

        provider = self.provider_combo.currentData()
        settings = {
            'provider': provider,
            'temperature': self.temperature_slider.value() / 10,
            'providers': dict(self._provider_configs),
        }
        # Ensure all providers have a dict entry
        for pid, _ in PROVIDERS:
            settings['providers'].setdefault(pid, {})

        logger.debug(f"Saving settings: provider={provider}, temp={settings['temperature']}")
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f, indent=2)
        logger.info("Settings saved successfully")

    def save_and_accept(self):
        self.save_settings()
        self.accept()

    def get_settings(self):
        """Return flat settings dict for the active provider (consumed by api_client)."""
        self._save_current_provider_fields()
        provider = self.provider_combo.currentData()
        cfg = self._provider_configs.get(provider, {})

        result = {
            'provider': provider,
            'api_key': cfg.get('api_key', ''),
            'model': cfg.get('model', DEFAULT_MODEL),
            'temperature': self.temperature_slider.value() / 10,
        }
        if provider == 'openai_compatible':
            result['endpoint'] = cfg.get('endpoint', OPENAI_DEFAULT_ENDPOINT)
            result['has_vision'] = cfg.get('has_vision', False)
        return result
