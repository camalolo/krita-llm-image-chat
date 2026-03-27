"""Procedural texture tool: generate noise, perlin, voronoi, and other patterns."""

import numpy as np
from ._registry import register_handler, TOOL_SCHEMAS, SCHEMA_BLEND_MODES, _get_document
from ..pixel_ops import (
    hex_to_rgba, perlin_noise_2d, voronoi_2d, fractal_noise_2d,
    create_blank_layer, write_pixels,
)
from ..config import logger

TOOL_SCHEMAS["procedural_texture"] = {
    "type": "function",
    "function": {
        "name": "procedural_texture",
        "description": (
            "Generate a procedural texture as a new layer. Non-destructive. "
            "color_1 and color_2 define the gradient endpoints, scale controls pattern size."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "texture": {
                    "type": "string",
                    "enum": [
                        "noise", "perlin", "voronoi", "gradient", "checker",
                        "clouds", "dots", "wood_grain", "marble",
                    ],
                    "description": "Texture type to generate",
                },
                "color_1": {"type": "string", "description": "First hex color (default '#000000')"},
                "color_2": {"type": "string", "description": "Second hex color (default '#FFFFFF')"},
                "scale": {"type": "number", "description": "Pattern scale (default 100)", "minimum": 1},
                "intensity": {"type": "number", "description": "Opacity intensity 0-100 (default 80)", "minimum": 0, "maximum": 100},
                "opacity": {"type": "number", "description": "Layer opacity 0-100 (default 100)", "minimum": 0, "maximum": 100},
                "blend_mode": {"type": "string", "enum": SCHEMA_BLEND_MODES, "description": "Blend mode (default 'normal'). Also supports: darken, lighten, color-dodge, color-burn, hard-light, exclusion, hue, saturation, erase"},
                "layer_name": {"type": "string", "description": "Name for the new texture layer"},
            },
            "required": ["texture"],
        },
    },
}


@register_handler("procedural_texture")
def handle_procedural_texture(args):
    doc = _get_document()
    w, h = doc.width(), doc.height()
    texture = args.get("texture", "noise")
    color_1 = args.get("color_1", "#000000")
    color_2 = args.get("color_2", "#FFFFFF")
    scale = args.get("scale", 100.0)
    if scale < 1:
        scale = 1
    intensity = args.get("intensity", 80)
    opacity = args.get("opacity", 100)
    blend_mode = args.get("blend_mode", "normal")
    new_name = args.get("layer_name", f"Texture {texture}")

    c1 = hex_to_rgba(color_1)
    c2 = hex_to_rgba(color_2)
    c1_arr = np.array([c1[0] * 255, c1[1] * 255, c1[2] * 255, 255], dtype=np.float64)
    c2_arr = np.array([c2[0] * 255, c2[1] * 255, c2[2] * 255, 255], dtype=np.float64)

    xs = np.arange(w, dtype=np.float64)
    ys = np.arange(h, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)

    if texture == "noise":
        pattern = np.random.randint(0, 256, (h, w), dtype=np.uint8).astype(np.float64)
    elif texture == "perlin":
        pattern = perlin_noise_2d(w, h, scale) * 255.0
    elif texture == "voronoi":
        num_pts = max(2, int(scale / 5))
        pattern = voronoi_2d(w, h, num_pts) * 255.0
    elif texture == "gradient":
        pattern = (yy / max(h - 1, 1) * 255.0)
    elif texture == "checker":
        checker = ((xx.astype(np.int32) // int(scale)) + (yy.astype(np.int32) // int(scale))) % 2
        pattern = checker.astype(np.float64) * 255.0
    elif texture == "clouds":
        pattern = fractal_noise_2d(w, h, scale) * 255.0
    elif texture == "dots":
        grid_size = max(scale / 2, 2)
        cx = (np.floor(xx / grid_size) + 0.5) * grid_size
        cy = (np.floor(yy / grid_size) + 0.5) * grid_size
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        radius = grid_size * 0.35
        pattern = np.where(dist < radius, 255.0, 0.0)
    elif texture == "wood_grain":
        noise = perlin_noise_2d(w, h, scale * 3)
        pattern = (np.sin(xx / max(scale, 1) + noise * 5) * 0.5 + 0.5) * 255.0
    elif texture == "marble":
        perlin = perlin_noise_2d(w, h, scale)
        pattern = (np.sin(xx / max(scale, 1) + perlin * 10) * 0.5 + 0.5) * 255.0
    else:
        return {"success": False, "error": f"Unknown texture: {texture}"}

    np.clip(pattern, 0, 255, out=pattern)
    t = (pattern / 255.0)[:, :, np.newaxis]
    result = c1_arr[np.newaxis, np.newaxis, :] * (1 - t) + c2_arr[np.newaxis, np.newaxis, :] * t

    if intensity < 100:
        alpha = result[:, :, 3]
        result[:, :, 3] = alpha * (intensity / 100.0)
    np.clip(result, 0, 255, out=result)
    result = result.astype(np.uint8)

    new_layer = create_blank_layer(doc, new_name, w, h, opacity, blend_mode)
    write_pixels(new_layer, result, 0, 0, w, h, doc)
    doc.setActiveNode(new_layer)
    doc.refreshProjection()
    logger.info(f"Generated texture '{texture}' as layer '{new_name}'")
    return {"success": True, "message": f"Generated '{texture}' texture",
            "data": {"layer_name": new_name}}
