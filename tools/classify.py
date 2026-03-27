"""Tool classification and schema generation.

classify_tools() determines which subset of tools to send based on user message content.
generate_tools() builds the OpenAI-format tool schema list from TOOL_SCHEMAS registry.
"""

from ._registry import TOOL_SCHEMAS

CORE_TOOLS = ["image_info", "pick_color", "undo", "redo"]
CREATIVE_TOOLS = [
    "color_grade", "procedural_texture", "adjust",
    "remove_bg_color", "remove_background", "apply_lut", "apply_effect", "fill",
]
STRUCTURAL_TOOLS = [
    "layer", "layer_stack", "transform", "selection",
    "document", "export",
]

_CREATIVE_KEYWORDS = {
    "color", "grade", "texture", "noise", "blur", "sharpen", "effect",
    "filter", "warm", "cool", "vintage", "cinematic", "dramatic", "faded",
    "bright", "contrast", "saturat", "hue", "temperature", "vibrance",
    "gamma", "extract", "subject", "background", "adjust", "darken",
    "lighten", "posterize", "threshold", "desaturat", "invert", "emboss",
    "pixelat", "oil", "wave", "edge", "marble", "perlin", "voronoi",
    "checker", "dots", "cloud", "wood", "lut", "gradient",
    "pick", "sample", "erase_background",
}
_STRUCTURAL_KEYWORDS = {
    "layer", "group", "selection", "select", "crop", "resize", "scale",
    "rotate", "flip", "transform", "export", "save", "document", "merge",
    "flatten", "move", "duplicate", "delete", "rename", "new", "opacity",
    "blend", "visible", "hide", "show",
}


def classify_tools(user_message):
    """Classify user message to determine which tool subset to send.
    
    Returns:
        "creative" — if only creative keywords found
        "structural" — if only structural keywords found
        None — if ambiguous or no keywords (sends all tools)
    """
    if not user_message:
        return None
    lower = user_message.lower()
    has_creative = any(kw in lower for kw in _CREATIVE_KEYWORDS)
    has_structural = any(kw in lower for kw in _STRUCTURAL_KEYWORDS)
    if has_creative and not has_structural:
        return "creative"
    if has_structural and not has_creative:
        return "structural"
    return None


# ── generate_tools ──────────────────────────────────────────────────────────────

_cached_tools = None
_cached_tools_creative = None
_cached_tools_structural = None


def generate_tools(context=None):
    """Build OpenAI-format tool schema list from TOOL_SCHEMAS registry.
    
    Args:
        context: "creative", "structural", or None (all tools)
    
    Returns:
        List of tool schema dicts for the OpenAI API.
    """
    if context == "creative":
        global _cached_tools_creative
        if _cached_tools_creative is not None:
            return _cached_tools_creative
    elif context == "structural":
        global _cached_tools_structural
        if _cached_tools_structural is not None:
            return _cached_tools_structural
    else:
        global _cached_tools
        if _cached_tools is not None:
            return _cached_tools

    # Schemas are already in full OpenAI format {"type": "function", "function": {...}}
    tools = list(TOOL_SCHEMAS.values())

    _cached_tools = tools

    creative_names = set(CORE_TOOLS + CREATIVE_TOOLS)
    structural_names = set(CORE_TOOLS + STRUCTURAL_TOOLS)

    _cached_tools_creative = [t for t in tools
                              if t["function"]["name"] in creative_names]
    _cached_tools_structural = [t for t in tools
                                if t["function"]["name"] in structural_names]

    if context == "creative":
        return _cached_tools_creative
    elif context == "structural":
        return _cached_tools_structural
    return tools
