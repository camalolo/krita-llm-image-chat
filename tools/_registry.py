"""Shared infrastructure for the tools package.

Provides:
- TOOL_HANDLERS / TOOL_SCHEMAS registries
- register_handler decorator
- execute_tool dispatcher
- Shared document/layer helpers
- Shared mutable state (selection backup, property backup)
- Constants (BLEND_MODES, SCHEMA_BLEND_MODES, anchor/direction enums)
"""

from krita import Krita, Selection
from PyQt5.QtGui import QColor

from ..config import logger, log_exception
from ..pixel_ops import (
    read_pixels,
    hex_to_managed_color,
    create_blank_layer,
    get_channels,
)

# ── Constants ────────────────────────────────────────────────────────────────────

BLEND_MODES = [
    "normal", "multiply", "screen", "overlay", "darken",
    "lighten", "color-dodge", "color-burn", "hard-light",
    "soft-light", "difference", "exclusion", "hue",
    "saturation", "color", "luminosity", "erase",
]

SCHEMA_BLEND_MODES = [
    "normal", "multiply", "screen", "overlay", "soft-light",
    "difference", "color", "luminosity",
]

ANCHOR_OPTIONS = [
    "center", "top-left", "top", "top-right",
    "left", "right", "bottom-left", "bottom", "bottom-right",
]

MOVE_DIRECTIONS = ["up", "down", "top", "bottom"]

# ── Registries ───────────────────────────────────────────────────────────────────

TOOL_HANDLERS = {}
TOOL_SCHEMAS = {}

# ── Shared mutable state ─────────────────────────────────────────────────────────

_last_property_backup = None
_last_selection_backup = None


# ── Decorator ────────────────────────────────────────────────────────────────────

def register_handler(name):
    """Decorator to register a tool handler function in TOOL_HANDLERS."""
    def decorator(func):
        TOOL_HANDLERS[name] = func
        return func
    return decorator


# ── Shared helpers ───────────────────────────────────────────────────────────────

def _get_document():
    krita = Krita.instance()
    doc = krita.activeDocument()
    if not doc:
        logger.error("No active document found")
        raise Exception("No active document")
    logger.debug(
        f"Got document: {doc.fileName() if doc.fileName() else 'untitled'}, "
        f"size: {doc.width()}x{doc.height()}"
    )
    return doc


def _find_layer(doc, layer_name=None):
    if layer_name:
        logger.debug(f"Finding layer by name: {layer_name}")
        result = _find_layer_recursive(doc.rootNode(), layer_name)
        if result:
            logger.debug(f"Found layer: {layer_name}")
            return result
        logger.error(f"Layer not found: {layer_name}")
        raise Exception(f"Layer not found: {layer_name}")
    layer = doc.activeNode()
    if not layer:
        logger.error("No active layer found")
        raise Exception("No active layer")
    logger.debug(f"Using active layer: {layer.name()}")
    return layer


def _find_layer_recursive(node, layer_name):
    for child in node.childNodes():
        if child.name() == layer_name:
            return child
        if child.type() == "grouplayer":
            result = _find_layer_recursive(child, layer_name)
            if result:
                return result
    return None


def _backup_selection(doc):
    global _last_selection_backup
    sel = doc.selection()
    if sel:
        _last_selection_backup = {
            "pixel_data": bytes(sel.pixelData(sel.x(), sel.y(), sel.width(), sel.height())),
            "x": sel.x(),
            "y": sel.y(),
            "width": sel.width(),
            "height": sel.height(),
        }
    else:
        _last_selection_backup = None


def _restore_selection(doc):
    global _last_selection_backup
    if _last_selection_backup is None:
        return False
    backup = _last_selection_backup
    sel = Selection()
    sel.select(backup["x"], backup["y"], backup["width"], backup["height"], 255)
    sel.setPixelData(backup["pixel_data"], backup["x"], backup["y"], backup["width"], backup["height"])
    doc.setSelection(sel)
    _last_selection_backup = None
    doc.refreshProjection()
    logger.info("Restored selection from backup")
    return True


def _read_active_for_art(args):
    """Read pixels from the active layer. Returns (doc, layer, arr, x, y, w, h) or error dict."""
    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        raise Exception("No active layer")
    arr, x, y, w, h = read_pixels(layer, doc)
    if arr.size == 0:
        return {"success": False, "error": f"Active layer '{layer.name()}' has no pixel data (empty bounds: {w}x{h}). Cannot perform operation."}
    return doc, layer, arr, x, y, w, h


# ── Dispatcher ───────────────────────────────────────────────────────────────────

def execute_tool(tool_name, args):
    logger.debug(f"execute_tool called: {tool_name}, args: {args}")
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        logger.error(f"Unknown tool: {tool_name}. Available: {list(TOOL_HANDLERS.keys())}")
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    try:
        logger.debug(f"Calling handler for {tool_name}")
        result = handler(args if args else {})
        logger.debug(f"Handler returned: {result}")
        if not isinstance(result, dict):
            logger.warning(f"Handler for {tool_name} returned non-dict: {type(result).__name__}: {result}")
            result = {"success": True, "message": str(result)} if result else {"success": True}
        return result
    except Exception as e:
        log_exception(e, f"execute_tool({tool_name})")
        return {"success": False, "error": str(e)}
