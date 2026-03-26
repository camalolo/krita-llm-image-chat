import os
import logging
from logging.handlers import RotatingFileHandler
import traceback

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(PLUGIN_DIR, "llm_image_chat.log")
SETTINGS_PATH = os.path.join(PLUGIN_DIR, "settings.json")
HISTORY_PATH = os.path.join(PLUGIN_DIR, "history.json")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_DEFAULT_ENDPOINT = "http://localhost:11434/v1"
PROVIDERS = [("openrouter", "OpenRouter"), ("openai_compatible", "OpenAI-Compatible")]

RETRY_COUNT = 3
TIMEOUT_SECONDS = 60

MODELS = [
    ("mistralai/mistral-small-3.1-24b-instruct:free", True),
    ("nvidia/nemotron-nano-12b-v2-vl:free", True),
    ("nvidia/nemotron-3-super-120b-a12b:free", False),
    ("qwen/qwen3-coder:free", False),
    ("stepfun/step-3.5-flash:free", False),
    ("nvidia/nemotron-3-nano-30b-a3b:free", False),
    ("arcee-ai/trinity-mini:free", False),
    ("openai/gpt-oss-120b:free", False),
    ("z-ai/glm-4.5-air:free", False),
    ("meta-llama/llama-3.3-70b-instruct:free", False),
]

DEFAULT_MODEL = "mistralai/mistral-small-3.1-24b-instruct:free"

_VISION_MODEL_PATTERNS = (
    "vl", "vision", "llava", "gpt-4o", "gpt-4-turbo",
    "qwen-vl", "cogvlm", "glm-4v", "pixtral",
)


def model_supports_vision(model_id):
    for mid, has_vision in MODELS:
        if mid == model_id:
            return has_vision
    return False


def guess_model_has_vision(model_id):
    mid_lower = model_id.lower()
    return any(p in mid_lower for p in _VISION_MODEL_PATTERNS)


def migrate_settings(settings_dict):
    """Migrate old flat settings format to new provider-based format.
    
    Old format: {"api_key": "...", "model": "...", "temperature": 0.7}
    New format: {"provider": "openrouter", "temperature": 0.7, "providers": {...}}
    
    Returns a new dict (does not mutate input).
    """
    if "provider" in settings_dict:
        s = dict(settings_dict)
        if "providers" not in s:
            s["providers"] = {}
        for pid, _ in PROVIDERS:
            if pid not in s["providers"]:
                s["providers"][pid] = {}
        return s

    old_key = settings_dict.get("api_key", "")
    old_model = settings_dict.get("model", DEFAULT_MODEL)
    old_temp = settings_dict.get("temperature", 0.7)

    return {
        "provider": "openrouter",
        "temperature": old_temp,
        "providers": {
            "openrouter": {
                "api_key": old_key,
                "model": old_model,
            },
            "openai_compatible": {
                "api_key": "",
                "endpoint": OPENAI_DEFAULT_ENDPOINT,
                "model": "",
            },
        },
    }


SYSTEM_PROMPT = """You are a creative Krita image assistant with 16 tools for image manipulation.
CURRENT DOCUMENT INFO is injected below when available — you do NOT need to call image_info first unless the document has changed.
ARTISTIC TOOLS are non-destructive — they create new layers automatically. apply_effect is destructive (modifies in-place).
PARALLEL TOOL CALLS: When multiple independent operations are needed, make multiple tool calls in one response to save rounds.
WORKFLOW:
1. Read injected document info (if present). Call image_info only if document changed.
2. Make parallel tool calls for independent operations.
3. Plan to stay within the tool-call round limit.
4. Summarize what you did for the user."""




try:
    with open(LOG_PATH, 'w'):
        pass
except OSError:
    pass

_handler = RotatingFileHandler(
    LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=2, encoding='utf-8'
)
_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


def log_exception(e, context=""):
    logger.error(f"EXCEPTION in {context}: {type(e).__name__}: {str(e)}")
    logger.debug(traceback.format_exc())
