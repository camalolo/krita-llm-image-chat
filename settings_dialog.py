from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                              QLineEdit, QComboBox, QSlider, QLabel, QPushButton)
from PyQt5.QtCore import Qt
from .config import SETTINGS_PATH, MODELS, DEFAULT_MODEL, logger, log_exception
import json
import os


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
        for model_id, _ in MODELS:
            self.model_combo.addItem(model_id)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.model_note_label = QLabel("")
        self.model_note_label.setStyleSheet("color: #e67e22; font-style: italic; font-size: 11px;")
        model_layout = QVBoxLayout()
        model_layout.addWidget(self.model_combo)
        model_layout.addWidget(self.model_note_label)
        form_layout.addRow("Model:", model_layout)

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

    def _on_model_changed(self, index):
        if 0 <= index < len(MODELS):
            _, has_vision = MODELS[index]
            if not has_vision:
                self.model_note_label.setText("⚠ This model does not support vision — image will not be sent.")
            else:
                self.model_note_label.setText("✓ Supports vision and tools")
        else:
            self.model_note_label.setText("")

    def load_settings(self):
        logger.debug(f"SettingsDialog.load_settings() called, path: {SETTINGS_PATH}")
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r') as f:
                    settings = json.load(f)
                logger.debug(f"Loaded settings: model={settings.get('model')}, temp={settings.get('temperature')}, api_key={'*' * 8 if settings.get('api_key') else 'empty'}")
                self.api_key_edit.setText(settings.get('api_key', ''))
                model = settings.get('model', DEFAULT_MODEL)
                index = self.model_combo.findText(model)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
                self._on_model_changed(self.model_combo.currentIndex())
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
