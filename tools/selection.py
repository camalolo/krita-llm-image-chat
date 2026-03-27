"""selection tool – create, modify, query, and clear selections."""

from collections import deque

import numpy as np
from krita import Selection

from ._registry import (
    register_handler, TOOL_SCHEMAS,
    _get_document, _backup_selection,
)
from ..pixel_ops import read_pixels, get_channels
from ..config import logger


def _magic_select(doc, x, y, tolerance, contiguous=False):
    """Select pixels matching the color at (x, y) within tolerance.

    Args:
        doc: Active Krita document.
        x, y: Seed point in document-space coordinates.
        tolerance: Color distance threshold (0-255 Euclidean in RGB).
        contiguous: If True, only select connected pixels (flood fill).
    """
    layer = doc.activeNode()
    if layer is None:
        return {"success": False, "error": "No active layer"}

    arr, lx, ly, lw, lh = read_pixels(layer, doc)
    if arr.size == 0:
        return {"success": False, "error": "Layer has no pixel data"}

    channels = get_channels(doc)
    depth = doc.colorDepth().upper()

    # Normalize to U8 if needed (U16/F16/F32 → scale to 0-255)
    if depth == "U16":
        raw = arr.reshape(lh, lw, -1).view(np.uint16).astype(np.float32)
        u8 = (raw * (255.0 / 65535.0)).clip(0, 255).astype(np.uint8)
        u8 = u8[:, :, :channels]
    elif depth == "F16":
        raw = arr.reshape(lh, lw, -1).view(np.float16).astype(np.float32)
        u8 = (raw * 255.0).clip(0, 255).astype(np.uint8)
        u8 = u8[:, :, :channels]
    elif depth == "F32":
        raw_float = arr.reshape(lh, lw, -1).view(np.float32)
        u8 = (raw_float * 255.0).clip(0, 255).astype(np.uint8)
        u8 = u8[:, :, :channels]
    else:
        u8 = arr[:, :, :channels]

    # Clamp seed point to layer bounds
    sx = max(0, min(x - lx, lw - 1))
    sy = max(0, min(y - ly, lh - 1))

    seed = u8[sy, sx].astype(np.float32)

    # Vectorized Euclidean color distance (use only color channels, skip alpha)
    n_color = min(3, channels)  # GRAY=1, GRAYA=1, RGB=3, RGBA=3, CMYK=4→3
    rgb = u8[:, :, :n_color].astype(np.float32)
    dist = np.sqrt(np.sum((rgb - seed[:n_color]) ** 2, axis=2))

    tolerance = max(0, tolerance)
    mask = dist <= tolerance

    if contiguous:
        # BFS flood fill on the mask from seed, only traversing True pixels
        visited = np.zeros((lh, lw), dtype=bool)
        visited[sy, sx] = True
        queue = deque([(sy, sx)])
        while queue:
            cy, cx = queue.popleft()
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < lh and 0 <= nx < lw and not visited[ny, nx] and mask[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((ny, nx))
        mask = visited

    # Create Krita Selection from the boolean mask
    sel = Selection()
    sel.select(lx, ly, lw, lh, 255)
    sel_bytes = (mask.astype(np.uint8) * 255).tobytes()
    sel.setPixelData(sel_bytes, lx, ly, lw, lh)
    doc.setSelection(sel)

    pixel_count = int(mask.sum())
    return {"success": True, "message": f"Selected {pixel_count} pixels"}


TOOL_SCHEMAS["selection"] = {
    "type": "function",
    "function": {
        "name": "selection",
        "description": (
            "Manage selections. Actions: 'create' — make a new selection (type='rect' with x,y,w,h or type='all'); "
            "'select_by_color' — select pixels matching a color at (x,y) within tolerance (contiguous: "
            "only connected pixels); 'modify' — alter existing selection (modify_action: invert, feather, grow, shrink, smooth; "
            "value sets the modifier amount); 'clear' — remove selection; 'info' — get selection bounds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "select_by_color", "modify", "clear", "info"],
                    "description": "Selection action to perform",
                },
                "type": {
                    "type": "string",
                    "enum": ["all", "rect"],
                    "description": "Selection type for create action (default 'rect')",
                },
                "x": {"type": "integer", "description": "Left edge of rectangle (pixels)", "minimum": 0},
                "y": {"type": "integer", "description": "Top edge of rectangle (pixels)", "minimum": 0},
                "w": {"type": "integer", "description": "Width of rectangle (pixels)", "minimum": 0},
                "h": {"type": "integer", "description": "Height of rectangle (pixels)", "minimum": 0},
                "tolerance": {
                    "type": "integer",
                    "description": "Color distance tolerance for select_by_color (0=exact match, 255=everything, default 32)",
                    "minimum": 0,
                    "maximum": 255,
                },
                "contiguous": {
                    "type": "boolean",
                    "description": "For select_by_color: if true, only select pixels connected to the seed point (flood fill). Default false.",
                },
                "modify_action": {
                    "type": "string",
                    "enum": ["invert", "feather", "grow", "shrink", "smooth"],
                    "description": "Modification action for modify action",
                },
                "value": {"type": "number", "description": "Modifier value for feather/grow/shrink", "minimum": 0},
            },
            "required": ["action"],
        },
    },
}


@register_handler("selection")
def handle_selection(args):
    doc = _get_document()
    action = args.get("action", "create")

    if action == "create":
        _backup_selection(doc)
        sel_type = args.get("type", "rect")
        x = args.get("x", 0)
        y = args.get("y", 0)
        w = args.get("w", doc.width())
        h = args.get("h", doc.height())
        selection = Selection()
        if sel_type == "all":
            selection.select(0, 0, doc.width(), doc.height(), 255)
        elif sel_type == "rect":
            selection.select(x, y, w, h, 255)
        else:
            return {"success": False, "error": f"Unknown selection type: {sel_type}"}
        doc.setSelection(selection)
        logger.info(f"Created {sel_type} selection: ({x},{y},{w},{h})")
        return {"success": True, "message": f"Created {sel_type} selection"}

    elif action == "select_by_color":
        _backup_selection(doc)
        x = int(args.get("x", 0))
        y = int(args.get("y", 0))
        tolerance = int(args.get("tolerance", 32))
        contiguous = args.get("contiguous", False)
        return _magic_select(doc, x, y, tolerance, contiguous)

    elif action == "modify":
        _backup_selection(doc)
        modify_action = args.get("modify_action", "invert")
        value = args.get("value", 10)
        selection = doc.selection()
        if not selection:
            return {"success": False, "error": "No selection to modify"}
        if modify_action == "invert":
            selection.invert()
        elif modify_action == "feather":
            selection.feather(value)
        elif modify_action == "grow":
            selection.grow(value, value)
        elif modify_action == "shrink":
            selection.shrink(value, value)
        elif modify_action == "smooth":
            selection.smooth()
        else:
            return {"success": False, "error": f"Unknown modify action: {modify_action}"}
        doc.setSelection(selection)
        logger.info(f"Applied {modify_action} to selection")
        return {"success": True, "message": f"Applied {modify_action} to selection"}

    elif action == "clear":
        _backup_selection(doc)
        doc.setSelection(None)
        logger.info("Cleared selection")
        return {"success": True, "message": "Selection cleared"}

    elif action == "info":
        selection = doc.selection()
        if not selection:
            return {"success": False, "error": "No selection exists"}
        return {
            "success": True,
            "data": {
                "x": selection.x(),
                "y": selection.y(),
                "width": selection.width(),
                "height": selection.height(),
            },
        }

    return {"success": False, "error": f"Unknown selection action: {action}"}
