import os
import logging
from logging.handlers import RotatingFileHandler
import traceback

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(PLUGIN_DIR, "llm_image_chat.log")
SETTINGS_PATH = os.path.join(PLUGIN_DIR, "settings.json")
API_URL = "https://openrouter.ai/api/v1/chat/completions"

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


def model_supports_vision(model_id):
    for mid, has_vision in MODELS:
        if mid == model_id:
            return has_vision
    return False


def get_valid_model_id(model_id):
    """Return model_id if it's in the MODELS list, otherwise return DEFAULT_MODEL."""
    for mid, _ in MODELS:
        if mid == model_id:
            return model_id
    logger.warning(f"Unknown model '{model_id}', falling back to DEFAULT_MODEL")
    return DEFAULT_MODEL


SYSTEM_PROMPT = """You are a Krita image manipulation assistant with access to tools.

CAPABILITIES:
- Analyze images and modify them using provided tools
- Access to filters, layers, selections, document operations, colors, and fills
- Extract regions of an image onto separate layers (copy selection to new layer)
- Clear layer content, flip layers, rename layers, merge layers
- Create new documents, scale documents, export to files

TOOL USAGE:
- You MUST use the tool_calls API to call tools. Never output tool calls as text.
- Simply call tools naturally in your response — the API handles the formatting.
- Call image_info first to understand the current document state.
- You may call multiple tools sequentially. Results are fed back to you.
- If a tool fails, try alternative approaches.

COMPLEX OPERATIONS:
- To split an image: create selections for each region (selection_create), then copy each to a new layer (layer_copy_selection).
- To extract a quadrant: select the quadrant rect, call layer_copy_selection, clear selection, repeat for other quadrants.
- To composite layers: use layer_set_active to switch between layers, then layer_merge_down or layer_flatten.
- To export safely: use export_image with a NEW file path (cannot overwrite the open document).

WORKFLOW:
1. First call image_info to understand the document
2. Plan your approach based on the user's request
3. Call tools sequentially, checking results
4. Summarize what you did for the user

Respond naturally. Use tools when you need to modify the image or gather information."""


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
