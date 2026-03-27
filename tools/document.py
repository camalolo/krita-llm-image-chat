"""Document creation, cropping, undo, and redo."""

from krita import Krita, Selection
from . import _registry
from ._registry import (
    register_handler, TOOL_SCHEMAS,
    _get_document, _find_layer_recursive,
    _restore_selection,
)
from ..pixel_ops import restore_backup
from ..config import logger

TOOL_SCHEMAS["document"] = {
    "type": "function",
    "function": {
        "name": "document",
        "description": (
            "Document operations. Actions: 'new' — create a new document (width, height, name, resolution); "
            "'crop' — crop document to a rectangle (x, y, w, h) or to the current selection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["new", "crop"],
                    "description": "Document action to perform",
                },
                "width": {"type": "integer", "description": "Width in pixels (for new, default 1920)", "minimum": 1},
                "height": {"type": "integer", "description": "Height in pixels (for new, default 1080)", "minimum": 1},
                "name": {"type": "string", "description": "Document name for new action"},
                "resolution": {"type": "number", "description": "Resolution in PPI for new action (default 72)", "minimum": 1},
                "x": {"type": "number", "description": "Crop left edge (pixels)"},
                "y": {"type": "number", "description": "Crop top edge (pixels)"},
                "w": {"type": "number", "description": "Crop width (pixels)"},
                "h": {"type": "number", "description": "Crop height (pixels)"},
            },
            "required": ["action"],
        },
    },
}

TOOL_SCHEMAS["undo"] = {
    "type": "function",
    "function": {
        "name": "undo",
        "description": "Undo the last operation. Checks filter backup first, then falls back to Krita undo.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

TOOL_SCHEMAS["redo"] = {
    "type": "function",
    "function": {
        "name": "redo",
        "description": "Redo the last undone operation.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

@register_handler("document")
def handle_document(args):
    action = args.get("action")

    if action == "new":
        krita = Krita.instance()
        width = args.get("width", 1920)
        height = args.get("height", 1080)
        name = args.get("name", "Untitled")
        resolution = args.get("resolution", 72.0)
        if width < 1 or height < 1:
            return {"success": False, "error": "Width and height must be at least 1"}
        doc = krita.createDocument(width, height, name, "RGBA", "U8", "sRGB-elle-v2-srgbtrc.icc", resolution)
        if not doc:
            return {"success": False, "error": "Failed to create new document"}
        window = krita.activeWindow()
        if window:
            window.addView(doc)
        logger.info(f"Created document '{name}' ({width}x{height})")
        return {"success": True, "message": f"Created document '{name}' ({width}x{height})",
                "data": {"width": width, "height": height, "name": name}}

    elif action == "crop":
        doc = _get_document()
        x = args.get("x")
        y = args.get("y")
        w = args.get("w")
        h = args.get("h")
        if x is not None and y is not None and w is not None and h is not None:
            selection = Selection()
            selection.select(int(x), int(y), int(w), int(h), 255)
            doc.setSelection(selection)
        else:
            selection = doc.selection()
            if not selection:
                return {"success": False, "error": "No bounds specified and no selection exists"}
        krita_action = Krita.instance().action("resizeimagetoselection")
        if krita_action:
            krita_action.trigger()
            doc.refreshProjection()
            logger.info("Cropped document")
            return {"success": True, "message": "Cropped document to selection"}
        return {"success": False, "error": "Trim-to-selection action not available"}

    return {"success": False, "error": f"Unknown document action: {action}"}

@register_handler("undo")
def handle_undo(args):
    doc = _get_document()
    layer = doc.activeNode()

    if layer:
        layer_name = layer.name()
        if restore_backup(layer_name, layer, doc):
            doc.refreshProjection()
            logger.info(f"Reverted filter on layer '{layer_name}' from backup")
            return {"success": True, "message": f"Reverted filter on layer '{layer_name}'"}

    if _registry._last_property_backup is not None:
        backup = _registry._last_property_backup
        target = _find_layer_recursive(doc.rootNode(), backup["layer_name"])
        if target:
            target.setOpacity(backup["prev_opacity"])
            target.setBlendingMode(backup["prev_blend_mode"])
            target.setVisible(backup["prev_visible"])
            _registry._last_property_backup = None
            doc.refreshProjection()
            logger.info(f"Reverted property changes on '{backup['layer_name']}'")
            return {"success": True, "message": f"Reverted property changes on '{backup['layer_name']}'"}

    if _restore_selection(doc):
        return {"success": True, "message": "Restored selection from backup"}

    krita = Krita.instance()
    action = krita.action("edit_undo")
    if not action:
        return {"success": False, "error": "Undo action not available"}
    if not action.isEnabled():
        return {"success": False, "error": "Nothing to undo"}
    action.trigger()
    logger.info("Performed Krita undo")
    return {"success": True, "message": "Undo performed"}

@register_handler("redo")
def handle_redo(args):
    krita = Krita.instance()
    action = krita.action("edit_redo")
    if not action:
        return {"success": False, "error": "Redo action not available"}
    if not action.isEnabled():
        return {"success": False, "error": "Nothing to redo"}
    action.trigger()
    logger.info("Performed redo")
    return {"success": True, "message": "Redo performed"}
