"""Color grading tool: apply 10 preset grading styles non-destructively."""

import numpy as np
from ._registry import register_handler, TOOL_SCHEMAS, _read_active_for_art
from ..pixel_ops import (
    create_blank_layer, write_pixels,
    adjust_contrast, adjust_saturation,
)
from ..config import logger


def _color_grade_warm(arr, blend):
    graded = arr.astype(np.float64)
    graded[:, :, 0] *= 1.1
    graded[:, :, 2] *= 0.9
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded * blend).astype(np.uint8)


def _color_grade_cool(arr, blend):
    graded = arr.astype(np.float64)
    graded[:, :, 0] *= 0.9
    graded[:, :, 2] *= 1.1
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded * blend).astype(np.uint8)


def _color_grade_vintage(arr, blend):
    graded = arr.astype(np.float64)
    gray = 0.299 * graded[:, :, 0] + 0.587 * graded[:, :, 1] + 0.114 * graded[:, :, 2]
    graded[:, :, :3] = gray[:, :, np.newaxis] + (graded[:, :, :3] - gray[:, :, np.newaxis]) * 0.7
    graded[:, :, 0] *= 1.05
    graded[:, :, 2] *= 0.95
    dark_mask = graded[:, :, :3].mean(axis=2) < 128
    for c in range(3):
        graded[:, :, c] = np.where(dark_mask, graded[:, :, c] + 15, graded[:, :, c])
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded * blend).astype(np.uint8)


def _color_grade_cinematic(arr, blend):
    graded = arr.astype(np.float64)
    r, g, b = graded[:, :, 0], graded[:, :, 1], graded[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    t = (lum - 128.0) / 128.0
    t = np.clip(t, -1, 1)
    graded[:, :, 0] = r - t * 20
    graded[:, :, 1] = g - np.abs(t) * 5
    graded[:, :, 2] = b + t * 25
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded * blend).astype(np.uint8)


def _color_grade_dramatic(arr, blend):
    graded = adjust_contrast(arr, 30)
    graded = adjust_saturation(graded, -20)
    graded = graded.astype(np.float64)
    gray = 0.299 * graded[:, :, 0] + 0.587 * graded[:, :, 1] + 0.114 * graded[:, :, 2]
    dark = gray < 128
    graded[:, :, 2] = np.where(dark, graded[:, :, 2] + 10, graded[:, :, 2])
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded.astype(np.float64) * blend).astype(np.uint8)


def _color_grade_faded(arr, blend):
    graded = adjust_contrast(arr, -20)
    graded = graded.astype(np.float64)
    graded[:, :, :3] += 20
    graded = adjust_saturation(graded.astype(np.uint8), -10)
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded.astype(np.float64) * blend).astype(np.uint8)


def _color_grade_moody(arr, blend):
    graded = arr.astype(np.float64)
    graded[:, :, :3] -= 15
    gray = 0.299 * graded[:, :, 0] + 0.587 * graded[:, :, 1] + 0.114 * graded[:, :, 2]
    graded[:, :, :3] = gray[:, :, np.newaxis] + (graded[:, :, :3] - gray[:, :, np.newaxis]) * 0.9
    factor = (259 * (20 + 255)) / (255 * (259 - 20))
    graded[:, :, :3] = factor * (graded[:, :, :3] - 128.0) + 128.0
    graded[:, :, 2] += 8
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded.astype(np.float64) * blend).astype(np.uint8)


def _color_grade_cross_process(arr, blend):
    graded = arr.astype(np.float64)
    graded[:, :, 1] *= 1.15
    gray = 0.299 * graded[:, :, 0] + 0.587 * graded[:, :, 1] + 0.114 * graded[:, :, 2]
    mid_mask = (gray > 80) & (gray < 180)
    sat_boost = np.ones_like(gray)
    sat_boost[mid_mask] = 1.2
    graded[:, :, 0] = gray + (graded[:, :, 0] - gray) * sat_boost
    graded[:, :, 1] = gray + (graded[:, :, 1] - gray) * sat_boost
    graded[:, :, 2] = gray + (graded[:, :, 2] - gray) * sat_boost
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded.astype(np.float64) * blend).astype(np.uint8)


def _color_grade_teal_orange(arr, blend):
    graded = arr.astype(np.float64)
    r, g, b = graded[:, :, 0], graded[:, :, 1], graded[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    t = np.clip(lum / 255.0, 0, 1)
    shadow = np.array([0, 128, 180], dtype=np.float64)
    highlight = np.array([255, 140, 50], dtype=np.float64)
    target = shadow[np.newaxis, np.newaxis, :] * (1 - t[:, :, np.newaxis]) + highlight[np.newaxis, np.newaxis, :] * t[:, :, np.newaxis]
    graded[:, :, :3] = graded[:, :, :3] * 0.5 + target * 0.5
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded.astype(np.float64) * blend).astype(np.uint8)


def _color_grade_noir(arr, blend):
    graded = arr.astype(np.float64)
    gray = 0.299 * graded[:, :, 0] + 0.587 * graded[:, :, 1] + 0.114 * graded[:, :, 2]
    graded[:, :, 0] = gray
    graded[:, :, 1] = gray
    graded[:, :, 2] = gray
    graded = graded.astype(np.uint8)
    graded = adjust_contrast(graded, 50)
    h_val, w_val = graded.shape[:2]
    cy, cx = h_val / 2.0, w_val / 2.0
    ys = np.arange(h_val)[:, np.newaxis]
    xs = np.arange(w_val)[np.newaxis, :]
    dist = np.sqrt(((xs - cx) / cx) ** 2 + ((ys - cy) / cy) ** 2)
    vignette = np.clip(1.0 - dist * 0.4, 0.4, 1.0)
    graded = graded.astype(np.float64)
    graded[:, :, :3] *= vignette[:, :, np.newaxis]
    np.clip(graded, 0, 255, out=graded)
    return (arr.astype(np.float64) * (1 - blend) + graded.astype(np.float64) * blend).astype(np.uint8)


_COLOR_GRADE_FUNCS = {
    "warm": _color_grade_warm,
    "cool": _color_grade_cool,
    "vintage": _color_grade_vintage,
    "cinematic": _color_grade_cinematic,
    "dramatic": _color_grade_dramatic,
    "faded": _color_grade_faded,
    "moody": _color_grade_moody,
    "cross_process": _color_grade_cross_process,
    "teal_orange": _color_grade_teal_orange,
    "noir": _color_grade_noir,
}

TOOL_SCHEMAS["color_grade"] = {
    "type": "function",
    "function": {
        "name": "color_grade",
        "description": (
            "Apply a color grading style non-destructively. Creates a new layer with the graded result. "
            "intensity (0-100) controls blend strength."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "style": {
                    "type": "string",
                    "enum": [
                        "warm", "cool", "vintage", "cinematic", "dramatic",
                        "faded", "moody", "cross_process", "teal_orange", "noir",
                    ],
                    "description": "Color grading style",
                },
                "intensity": {"type": "number", "description": "Grade intensity 0-100 (default 60)", "minimum": 0, "maximum": 100},
                "layer_name": {"type": "string", "description": "Name for the new graded layer"},
            },
            "required": ["style"],
        },
    },
}


@register_handler("color_grade")
def handle_color_grade(args):
    result = _read_active_for_art(args)
    if isinstance(result, dict):
        return result
    doc, layer, arr, x, y, w, h = result
    style = args.get("style", "warm")
    if "intensity" in args:
        if not isinstance(args["intensity"], (int, float)):
            return {"success": False, "error": f"'intensity' must be a number, got {type(args['intensity']).__name__}: {args['intensity']!r}"}
        intensity = args["intensity"]
    else:
        intensity = 60

    grade_func = _COLOR_GRADE_FUNCS.get(style)
    if not grade_func:
        return {"success": False, "error": f"Unknown color grade style: {style}. Available: {list(_COLOR_GRADE_FUNCS.keys())}"}

    new_name = args.get("layer_name", f"Color Grade {style}")
    blend = intensity / 100.0
    result = grade_func(arr, blend)

    new_layer = create_blank_layer(doc, new_name, w, h)
    write_pixels(new_layer, result, x, y, w, h, doc)
    doc.setActiveNode(new_layer)
    doc.refreshProjection()
    logger.info(f"Applied color grade '{style}' (intensity={intensity})")
    return {"success": True, "message": f"Applied '{style}' color grade (intensity={intensity})",
            "data": {"layer_name": new_name}}
