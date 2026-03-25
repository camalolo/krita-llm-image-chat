import os
import logging
from logging.handlers import RotatingFileHandler
import traceback

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(PLUGIN_DIR, "llm_image_chat.log")
SETTINGS_PATH = os.path.join(PLUGIN_DIR, "settings.json")
HISTORY_PATH = os.path.join(PLUGIN_DIR, "history.json")
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


SYSTEM_PROMPT = """You are a creative Krita image assistant. You have 17 tools for image manipulation.

IMPORTANT: Call image_info first to understand the document.

ARTISTIC TOOLS (non-destructive — each creates a new layer):
- color_grade: Apply a cinematic color look (warm, cool, vintage, cinematic, dramatic, faded, moody, cross_process, teal_orange, noir). Set intensity to control strength.
- procedural_texture: Generate textures (noise, perlin, voronoi, gradient, checker, clouds, dots, wood_grain, marble). Set color_1/color_2, scale, opacity, blend_mode.
- adjust: Color corrections on a new layer — brightness, contrast, saturation, hue_shift, temperature, vibrance, gamma. All params optional.
- extract_subject: Remove background in one call. Auto-detects from corners or set target_color. Set threshold and softness.
- apply_lut: Custom color grading via JSON control points.

INFRASTRUCTURE TOOLS:
- selection: Create/modify/clear/get info on selections. Actions: create (all/rect), modify (invert/feather/grow/shrink/smooth), clear, info.
- layer: Create/delete/duplicate/rename/set_active layers. Supports paint, group, vector types with opacity and blend_mode.
- layer_properties: Set layer opacity, blend_mode, visible. All optional — only sets what you provide.
- layer_stack: Move layers (up/down/top/bottom or absolute position), merge_down, flatten, extract_selection.
- transform: Resize/scale/rotate/flip documents or layers. Use scope parameter. Resize has scale_content bool.
- fill: Fill selection or layer with a color. Pass color as hex (e.g. '#FF0000').
- apply_effect: Visual effects by name — blur, sharpen, noise, edge_detect, emboss, pixelate, brightness_contrast, hue_saturation, color_balance, invert, posterize, threshold, oil_paint, color_to_alpha, gaussian_blur, motion_blur. Set intensity 0-100. For color_to_alpha use target_color and threshold.
- document: Create new documents or crop to a rectangle/selection.
- export: Save (auto-named .kra + flat), export to path, or split into regions and export each.
- undo / redo: Undo/redo operations. Undo checks filter backups first.

WORKFLOW:
1. Call image_info first.
2. Use artistic tools for creative changes — they are non-destructive (create new layers).
3. Use infrastructure tools for document structure and basic operations.
4. Plan your approach to stay within the tool-call round limit.
5. Summarize what you did for the user."""




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
