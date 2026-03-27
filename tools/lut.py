"""Apply LUT tool: apply a color lookup table non-destructively."""

import json
import numpy as np
from ._registry import register_handler, TOOL_SCHEMAS, _read_active_for_art
from ..pixel_ops import create_blank_layer, write_pixels
from ..config import logger

TOOL_SCHEMAS["apply_lut"] = {
    "type": "function",
    "function": {
        "name": "apply_lut",
        "description": (
            "Apply a color lookup table non-destructively. Creates a new layer. "
            "lut is a JSON array of [r_in, g_in, b_in, r_out, g_out, b_out] control points."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lut": {
                    "type": "string",
                    "description": "JSON array of [r_in, g_in, b_in, r_out, g_out, b_out] control points",
                },
                "interpolation": {
                    "type": "string",
                    "enum": ["linear", "smooth"],
                    "description": "Interpolation method (default 'smooth')",
                },
                "layer_name": {"type": "string", "description": "Name for the new LUT layer"},
            },
            "required": ["lut"],
        },
    },
}


@register_handler("apply_lut")
def handle_apply_lut(args):
    result = _read_active_for_art(args)
    if isinstance(result, dict):
        return result
    doc, layer, arr, x, y, w, h = result
    lut_json = args.get("lut")
    interpolation = args.get("interpolation", "smooth")
    new_name = args.get("layer_name", "LUT Applied")

    if not lut_json:
        return {"success": False, "error": "lut is required (JSON string of control points)"}

    try:
        points = json.loads(lut_json)
    except (json.JSONDecodeError, TypeError) as e:
        return {"success": False, "error": f"Failed to parse lut JSON: {e}"}

    if not points or len(points) < 2:
        return {"success": False, "error": "lut must have at least 2 control points"}

    inputs = np.array([[p[0], p[1], p[2]] for p in points], dtype=np.float64)
    outputs = np.array([[p[3], p[4], p[5]] for p in points], dtype=np.float64)

    rgb = arr[:, :, :3].astype(np.float64)
    h_val, w_val, _ = rgb.shape
    rgb_flat = rgb.reshape(-1, 3)

    distances = np.sqrt(np.sum((rgb_flat[:, np.newaxis, :] - inputs[np.newaxis, :, :]) ** 2, axis=2))
    sorted_indices = np.argsort(distances, axis=1)
    idx0 = sorted_indices[:, 0]
    idx1 = sorted_indices[:, 1]

    d0 = distances[np.arange(len(rgb_flat)), idx0]
    d1 = distances[np.arange(len(rgb_flat)), idx1]
    total_dist = d0 + d1
    total_dist[total_dist == 0] = 1.0
    t = d0 / total_dist

    if interpolation == "smooth":
        t = t * t * (3.0 - 2.0 * t)

    out0 = outputs[idx0]
    out1 = outputs[idx1]
    result_rgb = out0 * (1 - t[:, np.newaxis]) + out1 * t[:, np.newaxis]
    np.clip(result_rgb, 0, 255, out=result_rgb)

    result = arr.copy()
    result[:, :, :3] = result_rgb.reshape(h_val, w_val, 3).astype(np.uint8)

    new_layer = create_blank_layer(doc, new_name, w, h)
    write_pixels(new_layer, result, x, y, w, h, doc)
    doc.setActiveNode(new_layer)
    doc.refreshProjection()
    logger.info(f"Applied LUT ({len(points)} control points, interpolation={interpolation})")
    return {"success": True, "message": f"Applied LUT to layer '{new_name}'",
            "data": {"layer_name": new_name}}
