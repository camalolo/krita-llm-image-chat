"""transform tool – resize, scale, rotate, flip documents and layers."""

from ._registry import (
    register_handler, TOOL_SCHEMAS, ANCHOR_OPTIONS,
    _get_document, _find_layer,
)
from ..pixel_ops import read_pixels, write_pixels
from ..config import logger

TOOL_SCHEMAS["transform"] = {
    "type": "function",
    "function": {
        "name": "transform",
        "description": (
            "Transform document or layer. Actions: 'resize' — change canvas size (width, height, anchor, scale_content); "
            "'scale' — scale image to new dimensions; 'rotate' — rotate by degrees; "
            "'flip' — mirror horizontally or vertically. scope: 'document' (default) for all actions. 'layer' only supported with flip action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["resize", "scale", "rotate", "flip"],
                    "description": "Transform action to perform",
                },
                "scope": {
                    "type": "string",
                    "enum": ["document", "layer"],
                    "description": "Target scope (default 'document')",
                },
                "width": {"type": "integer", "description": "New width in pixels", "minimum": 1},
                "height": {"type": "integer", "description": "New height in pixels", "minimum": 1},
                "anchor": {
                    "type": "string",
                    "enum": ANCHOR_OPTIONS,
                    "description": "Anchor point for resize (default 'center')",
                },
                "scale_content": {"type": "boolean", "description": "Scale existing content when resizing (default false)"},
                "degrees": {"type": "number", "description": "Rotation angle in degrees (-360 to 360)", "minimum": -360, "maximum": 360},
                "direction": {
                    "type": "string",
                    "enum": ["horizontal", "vertical"],
                    "description": "Flip direction",
                },
                "layer_name": {"type": "string", "description": "Target layer name when scope='layer'"},
            },
            "required": ["action"],
        },
    },
}


@register_handler("transform")
def handle_transform(args):
    doc = _get_document()
    action = args.get("action")
    scope = args.get("scope", "document")

    if action == "resize":
        width = args.get("width", doc.width())
        height = args.get("height", doc.height())
        anchor = args.get("anchor", "center")
        scale_content = args.get("scale_content", False)
        old_w, old_h = doc.width(), doc.height()
        anchor_map = {
            "center": ((width - old_w) // 2, (height - old_h) // 2),
            "top-left": (0, 0),
            "top": ((width - old_w) // 2, 0),
            "top-right": (width - old_w, 0),
            "left": (0, (height - old_h) // 2),
            "right": (width - old_w, (height - old_h) // 2),
            "bottom-left": (0, height - old_h),
            "bottom": ((width - old_w) // 2, height - old_h),
            "bottom-right": (width - old_w, height - old_h),
        }
        x_offset, y_offset = anchor_map.get(anchor, ((width - old_w) // 2, (height - old_h) // 2))

        if scope == "document":
            if scale_content:
                doc.scaleImage(width, height, doc.resolution(), doc.resolution(), "Bicubic")
            else:
                doc.resizeImage(x_offset, y_offset, width, height, doc.resolution())
            doc.refreshProjection()
            logger.info(f"Resized document to {width}x{height} (anchor={anchor}, scale_content={scale_content})")
            return {"success": True, "message": f"Resized document to {width}x{height}"}
        return {"success": False, "error": "Layer-level resize not yet supported. Use scope='document' or duplicate the layer first."}

    elif action == "scale":
        width = args.get("width", doc.width())
        height = args.get("height", doc.height())
        if scope == "document":
            doc.scaleImage(width, height, doc.resolution(), doc.resolution(), "Bicubic")
            doc.refreshProjection()
            logger.info(f"Scaled document to {width}x{height}")
            return {"success": True, "message": f"Scaled document to {width}x{height}"}
        return {"success": False, "error": "Layer-level scale not yet supported. Use scope='document' or duplicate the layer first."}

    elif action == "rotate":
        degrees = args.get("degrees", 0)
        degrees = max(-360, min(360, degrees))
        if scope == "document":
            doc.rotateImage(degrees)
            doc.refreshProjection()
            logger.info(f"Rotated document by {degrees} degrees")
            return {"success": True, "message": f"Rotated document by {degrees} degrees"}
        return {"success": False, "error": "Layer-level rotate not yet supported. Use scope='document' or duplicate the layer first."}

    elif action == "flip":
        direction = args.get("direction", "horizontal")
        if scope == "document":
            if direction == "horizontal":
                doc.mirrorImage()
            elif direction == "vertical":
                doc.mirrorImageVertical()
            else:
                return {"success": False, "error": f"Unknown flip direction: {direction}"}
            doc.refreshProjection()
            logger.info(f"Flipped document {direction}")
            return {"success": True, "message": f"Flipped document {direction}"}
        elif scope == "layer":
            layer = _find_layer(doc, args.get("layer_name"))
            arr, x, y, w, h = read_pixels(layer, doc)
            if direction == "horizontal":
                arr = arr[:, ::-1, :]
            elif direction == "vertical":
                arr = arr[::-1, :, :]
            else:
                return {"success": False, "error": f"Unknown flip direction: {direction}"}
            write_pixels(layer, arr, x, y, w, h, doc)
            doc.refreshProjection()
            logger.info(f"Flipped layer '{layer.name()}' {direction}")
            return {"success": True, "message": f"Flipped layer '{layer.name()}' {direction}"}

    return {"success": False, "error": f"Unknown transform action: {action}"}
