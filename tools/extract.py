"""Remove background color tool: chroma-key style color removal, non-destructive."""

import numpy as np
from ._registry import register_handler, TOOL_SCHEMAS, _read_active_for_art
from ..pixel_ops import hex_to_rgba, color_distance, create_blank_layer, write_pixels
from ..config import logger

TOOL_SCHEMAS["remove_bg_color"] = {
    "type": "function",
    "function": {
        "name": "remove_bg_color",
        "description": (
            "Remove a solid background color (chroma key). Only works for uniform/flat backgrounds "
            "(green screen, white backdrop, solid color). Does NOT detect or isolate subjects — "
            "it simply makes pixels matching the target color transparent. For natural/complex "
            "backgrounds this tool will not produce good results. Non-destructive (creates new layer). "
            "When target_color is omitted, auto-detects from image corners."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_color": {"type": "string", "description": "Hex color to remove from the image"},
                "threshold": {"type": "integer", "description": "Color distance threshold 0-255 (default 30)"},
                "softness": {"type": "number", "description": "Edge softness 0-100 (default 20)", "minimum": 0, "maximum": 100},
                "layer_name": {"type": "string", "description": "Name for the new extracted layer"},
            },
            "required": [],
        },
    },
}


@register_handler("remove_bg_color")
def handle_remove_bg_color(args):
    result = _read_active_for_art(args)
    if isinstance(result, dict):
        return result
    doc, layer, arr, x, y, w, h = result
    target_hex = args.get("target_color")
    threshold = args.get("threshold", 30)
    softness = args.get("softness", 20)
    new_name = args.get("layer_name", "Removed BG")

    if target_hex:
        tr, tg, tb, _ = hex_to_rgba(target_hex)
        target_r, target_g, target_b = tr * 255, tg * 255, tb * 255
    else:
        tl = arr[0, 0, :3].astype(np.float64)
        tr_px = arr[0, -1 if w > 1 else 0, :3].astype(np.float64)
        bl = arr[-1 if h > 1 else 0, 0, :3].astype(np.float64)
        br = arr[-1 if h > 1 else 0, -1 if w > 1 else 0, :3].astype(np.float64)
        avg = (tl + tr_px + bl + br) / 4.0
        target_r, target_g, target_b = avg[0], avg[1], avg[2]

    r_ch = arr[:, :, 0].astype(np.float64)
    g_ch = arr[:, :, 1].astype(np.float64)
    b_ch = arr[:, :, 2].astype(np.float64)
    dist = color_distance(r_ch, g_ch, b_ch, target_r, target_g, target_b)

    alpha = np.where(
        dist < threshold,
        0.0,
        np.where(
            dist > threshold + softness,
            255.0,
            ((dist - threshold) / max(softness, 0.01)) * 255.0
        )
    )
    np.clip(alpha, 0, 255, out=alpha)

    result = arr.copy()
    if result.shape[2] >= 4:
        result[:, :, 3] = alpha.astype(np.uint8)
    else:
        result = np.dstack([result, alpha.astype(np.uint8)])

    new_layer = create_blank_layer(doc, new_name, w, h)
    write_pixels(new_layer, result, x, y, w, h, doc)
    doc.setActiveNode(new_layer)
    doc.refreshProjection()
    logger.info(f"Removed bg color (threshold={threshold}, softness={softness})")
    return {"success": True, "message": f"Removed background color to layer '{new_name}'",
            "data": {"layer_name": new_name}}
