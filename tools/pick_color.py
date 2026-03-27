"""Pick color tool: sample pixel color at (x, y) on the active layer."""

import numpy as np
from ._registry import register_handler, TOOL_SCHEMAS, _get_document
from ..pixel_ops import read_pixels, get_channels, rgba_to_hex
from ..config import logger

TOOL_SCHEMAS["pick_color"] = {
    "type": "function",
    "function": {
        "name": "pick_color",
        "description": (
            "Sample the color of a pixel at the given (x, y) coordinates on the active layer. "
            "Returns the hex color, individual R/G/B/A values, and the pixel position."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate of the pixel to sample"},
                "y": {"type": "integer", "description": "Y coordinate of the pixel to sample"},
            },
            "required": ["x", "y"],
        },
    },
}


@register_handler("pick_color")
def handle_pick_color(args):
    x = int(args.get("x", 0))
    y = int(args.get("y", 0))

    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        return {"success": False, "error": "No active layer"}

    arr, lx, ly, lw, lh = read_pixels(layer, doc)
    if arr.size == 0:
        return {"success": False, "error": f"Layer '{layer.name()}' has no pixel data"}

    sx = x - lx
    sy = y - ly
    if sx < 0 or sy < 0 or sy >= lh or sx >= lw:
        return {"success": False, "error": f"Coordinates ({x}, {y}) are outside layer bounds ({lx}, {ly}, {lx + lw}, {ly + lh})"}

    depth = doc.colorDepth().upper()
    channels = get_channels(doc)
    pixel = arr[sy, sx]

    if depth == "U8":
        channel_values = [int(pixel[c]) for c in range(channels)]
    elif depth == "U16":
        raw = pixel.tobytes()
        vals = np.frombuffer(raw, dtype=np.uint16)
        channel_values = [int(np.clip(vals[c] * 255.0 / 65535.0, 0, 255)) for c in range(channels)]
    elif depth == "F16":
        raw = pixel.tobytes()
        vals = np.frombuffer(raw, dtype=np.float16)
        channel_values = [int(np.clip(vals[c] * 255.0, 0, 255)) for c in range(channels)]
    elif depth == "F32":
        raw = pixel.tobytes()
        vals = np.frombuffer(raw, dtype=np.float32)
        channel_values = [int(np.clip(vals[c] * 255.0, 0, 255)) for c in range(channels)]
    else:
        channel_values = [int(pixel[c]) for c in range(channels)]

    r = int(np.clip(channel_values[0], 0, 255)) if len(channel_values) > 0 else 0
    g = int(np.clip(channel_values[1], 0, 255)) if len(channel_values) > 1 else 0
    b = int(np.clip(channel_values[2], 0, 255)) if len(channel_values) > 2 else 0
    a = int(np.clip(channel_values[3], 0, 255)) if len(channel_values) > 3 else 255

    hex_str = rgba_to_hex(r / 255.0, g / 255.0, b / 255.0, a / 255.0)

    logger.info(f"Picked color at ({x}, {y}): {hex_str} R={r} G={g} B={b} A={a}")
    return {
        "success": True,
        "data": {"x": x, "y": y, "hex": hex_str, "r": r, "g": g, "b": b, "a": a},
    }
