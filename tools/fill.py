"""fill tool – fill active layer or selection with a color."""

from krita import Krita

from ._registry import register_handler, TOOL_SCHEMAS, _get_document
from ..pixel_ops import hex_to_managed_color
from ..config import logger

TOOL_SCHEMAS["fill"] = {
    "type": "function",
    "function": {
        "name": "fill",
        "description": "Fill the active layer or selection with a color. Optionally set the color first.",
        "parameters": {
            "type": "object",
            "properties": {
                "color": {
                    "type": "string",
                    "description": "Hex color to fill with, e.g. '#FF0000'",
                },
                "type": {
                    "type": "string",
                    "enum": ["foreground", "background"],
                    "description": "Fill source (default 'foreground')",
                },
            },
            "required": [],
        },
    },
}


@register_handler("fill")
def handle_fill(args):
    doc = _get_document()
    fill_type = args.get("type", "foreground")
    color_hex = args.get("color")
    krita = Krita.instance()
    view = krita.activeWindow().activeView() if krita.activeWindow() else None
    if not view:
        return {"success": False, "error": "No active window/view"}

    if color_hex:
        color = hex_to_managed_color(color_hex, doc)
        if fill_type == "foreground":
            view.setForeGroundColor(color)
        elif fill_type == "background":
            view.setBackGroundColor(color)

    if fill_type == "foreground":
        action = Krita.instance().action("fill_selection_foreground_color")
    elif fill_type == "background":
        action = Krita.instance().action("fill_selection_background_color")
    else:
        action = Krita.instance().action("fill_selection_foreground_color")

    if action:
        action.trigger()
        doc.refreshProjection()
        logger.info(f"Filled with {fill_type}" + (f" color={color_hex}" if color_hex else ""))
        return {"success": True, "message": f"Filled with {fill_type}" + (f" color={color_hex}" if color_hex else "")}
    return {"success": False, "error": "Fill action not available"}
