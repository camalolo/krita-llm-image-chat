"""Image adjustment tool: brightness, contrast, saturation, hue, temperature, vibrance, gamma."""

import numpy as np
from ._registry import register_handler, TOOL_SCHEMAS, _get_document
from ..pixel_ops import (
    read_pixels, create_blank_layer, write_pixels,
    adjust_brightness, adjust_contrast, adjust_saturation,
    adjust_hue_shift, adjust_temperature, adjust_gamma,
)
from ..config import logger

TOOL_SCHEMAS["adjust"] = {
    "type": "function",
    "function": {
        "name": "adjust",
        "description": (
            "Apply image adjustments non-destructively. Creates a new layer with the adjusted result. "
            "Provide at least one adjustment parameter."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "brightness": {"type": "number", "description": "Brightness adjustment -100 to 100", "minimum": -100, "maximum": 100},
                "contrast": {"type": "number", "description": "Contrast adjustment -100 to 100", "minimum": -100, "maximum": 100},
                "saturation": {"type": "number", "description": "Saturation adjustment -100 to 100", "minimum": -100, "maximum": 100},
                "hue_shift": {"type": "number", "description": "Hue rotation -180 to 180 degrees", "minimum": -180, "maximum": 180},
                "temperature": {"type": "number", "description": "Color temperature -100 to 100", "minimum": -100, "maximum": 100},
                "vibrance": {"type": "number", "description": "Vibrance adjustment -100 to 100", "minimum": -100, "maximum": 100},
                "gamma": {"type": "number", "description": "Gamma correction 0.1 to 5.0", "minimum": 0.1, "maximum": 5.0},
                "layer_name": {"type": "string", "description": "Name for the new adjusted layer"},
            },
            "required": [],
        },
    },
}


@register_handler("adjust")
def handle_adjust(args):
    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        return {"success": False, "error": "No active layer"}

    brightness = args.get("brightness")
    contrast = args.get("contrast")
    saturation = args.get("saturation")
    hue_shift = args.get("hue_shift")
    temperature = args.get("temperature")
    vibrance = args.get("vibrance")
    gamma = args.get("gamma")

    if all(v is None for v in [brightness, contrast, saturation, hue_shift, temperature, vibrance, gamma]):
        return {"success": False, "error": "At least one adjustment parameter is required"}

    arr, x, y, w, h = read_pixels(layer, doc)
    applied = []

    if brightness is not None:
        arr = adjust_brightness(arr, brightness)
        applied.append(f"brightness={brightness}")
    if contrast is not None:
        arr = adjust_contrast(arr, contrast)
        applied.append(f"contrast={contrast}")
    if saturation is not None:
        arr = adjust_saturation(arr, saturation)
        applied.append(f"saturation={saturation}")
    if hue_shift is not None:
        arr = adjust_hue_shift(arr, hue_shift)
        applied.append(f"hue_shift={hue_shift}")
    if temperature is not None:
        arr = adjust_temperature(arr, temperature)
        applied.append(f"temperature={temperature}")
    if vibrance is not None:
        result = arr.astype(np.float64)
        gray = 0.299 * result[:, :, 0] + 0.587 * result[:, :, 1] + 0.114 * result[:, :, 2]
        max_chan = np.maximum(np.maximum(result[:, :, 0], result[:, :, 1]), result[:, :, 2])
        min_chan = np.minimum(np.minimum(result[:, :, 0], result[:, :, 1]), result[:, :, 2])
        current_sat = np.where((max_chan + min_chan) > 0,
                               (max_chan - min_chan) / (max_chan + min_chan), 0)
        vibrance_factor = 1.0 + (vibrance / 100.0) * (1.0 - current_sat)
        gray_3d = gray[:, :, np.newaxis]
        result[:, :, :3] = gray_3d + (result[:, :, :3] - gray_3d) * vibrance_factor[:, :, np.newaxis]
        np.clip(result, 0, 255, out=result)
        arr = result.astype(np.uint8)
        applied.append(f"vibrance={vibrance}")
    if gamma is not None:
        arr = adjust_gamma(arr, gamma)
        applied.append(f"gamma={gamma}")

    new_name = args.get("layer_name", f"Adjust ({', '.join(applied[:2])}{'...' if len(applied) > 2 else ''})")
    new_layer = create_blank_layer(doc, new_name, w, h)
    write_pixels(new_layer, arr, x, y, w, h, doc)
    doc.setActiveNode(new_layer)
    doc.refreshProjection()
    logger.info(f"Applied adjustments: {', '.join(applied)}")
    return {"success": True, "message": f"Applied: {', '.join(applied)}",
            "data": {"layer_name": new_name}}
