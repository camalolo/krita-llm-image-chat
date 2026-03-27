"""Remove background by seed-point fuzzy select + non-destructive layer copy."""

from collections import deque

import numpy as np

from ._registry import register_handler, TOOL_SCHEMAS, _read_active_for_art
from ..pixel_ops import create_blank_layer, write_pixels, get_channels
from ..config import logger


TOOL_SCHEMAS["remove_background"] = {
    "type": "function",
    "function": {
        "name": "remove_background",
        "description": (
            "Remove background by clicking a seed point on it. Fuzzy selects similar colors from "
            "the seed point (contiguous flood fill by default) and makes those pixels transparent "
            "on a new copy layer. Use for natural/complex backgrounds where remove_bg_color (chroma key) "
            "doesn't work. Non-destructive — creates a new layer with the background removed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate of the seed point on the background to remove"},
                "y": {"type": "integer", "description": "Y coordinate of the seed point on the background to remove"},
                "tolerance": {
                    "type": "integer",
                    "description": "Color distance tolerance 0-255 (default 32). Higher = more colors removed.",
                    "minimum": 0,
                    "maximum": 255,
                },
                "contiguous": {
                    "type": "boolean",
                    "description": "If true (default), only remove pixels connected to seed point (flood fill). If false, remove all matching pixels globally.",
                },
                "feather": {
                    "type": "number",
                    "description": "Edge feather radius in pixels (default 0). Smooths the boundary between removed and kept pixels.",
                    "minimum": 0,
                },
                "layer_name": {"type": "string", "description": "Name for the new layer (default 'Background Removed')"},
            },
            "required": ["x", "y"],
        },
    },
}


def _box_blur(arr, radius):
    """Simple box blur approximation of Gaussian blur."""
    result = arr.copy()
    for _ in range(max(1, int(radius))):
        padded = np.pad(result, 1, mode="edge")
        result = (
            padded[:-2, :-2]
            + padded[:-2, 1:-1]
            + padded[:-2, 2:]
            + padded[1:-1, :-2]
            + padded[1:-1, 1:-1]
            + padded[1:-1, 2:]
            + padded[2:, :-2]
            + padded[2:, 1:-1]
            + padded[2:, 2:]
        ) / 9.0
    return result


@register_handler("remove_background")
def handle_remove_background(args):
    result = _read_active_for_art(args)
    if isinstance(result, dict):
        return result
    doc, layer, arr, lx, ly, lw, lh = result

    x = int(args.get("x", 0))
    y = int(args.get("y", 0))
    tolerance = int(args.get("tolerance", 32))
    contiguous = args.get("contiguous", True)
    feather = float(args.get("feather", 0))
    layer_name = args.get("layer_name", "Background Removed")

    channels = get_channels(doc)
    depth = doc.colorDepth().upper()

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

    sx = max(0, min(x - lx, lw - 1))
    sy = max(0, min(y - ly, lh - 1))

    seed = u8[sy, sx].astype(np.float32)
    n_color = min(3, channels)
    rgb = u8[:, :, :n_color].astype(np.float32)
    dist = np.sqrt(np.sum((rgb - seed[:n_color]) ** 2, axis=2))

    tolerance = max(0, tolerance)
    mask = dist <= tolerance

    if contiguous:
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

    pixels_removed = int(mask.sum())

    if depth == "U8":
        result_u8 = arr.copy().astype(np.uint8)
        result_u8 = result_u8[:, :, :channels]
    else:
        if depth == "U16":
            raw = arr.reshape(lh, lw, -1).view(np.uint16).astype(np.float32)
            normed = (raw * (255.0 / 65535.0)).clip(0, 255).astype(np.uint8)
        elif depth == "F16":
            raw = arr.reshape(lh, lw, -1).view(np.float16).astype(np.float32)
            normed = (raw * 255.0).clip(0, 255).astype(np.uint8)
        elif depth == "F32":
            raw_float = arr.reshape(lh, lw, -1).view(np.float32)
            normed = (raw_float * 255.0).clip(0, 255).astype(np.uint8)
        else:
            normed = arr.copy().astype(np.uint8)
        normed = normed[:, :, :channels]
        result_u8 = np.dstack([normed, np.full((lh, lw), 255, dtype=np.uint8)]) if channels < 4 else normed

    if channels < 4 and depth == "U8":
        result_u8 = np.dstack([result_u8, np.full((lh, lw), 255, dtype=np.uint8)])

    if feather > 0:
        try:
            from scipy.ndimage import gaussian_filter

            removal_float = gaussian_filter(mask.astype(np.float64), sigma=feather)
        except ImportError:
            removal_float = _box_blur(mask.astype(np.float64), feather)

        np.clip(removal_float, 0.0, 1.0, out=removal_float)
        keep = 1.0 - removal_float

        result_u8[:, :, 3] = (
            result_u8[:, :, 3].astype(np.float64) * keep
        ).clip(0, 255).astype(np.uint8)
    else:
        result_u8[mask, 3] = 0

    if depth == "U16":
        out = (result_u8.astype(np.float32) * (65535.0 / 255.0)).clip(0, 65535).astype(np.uint16)
        result_arr = out.view(np.uint8).reshape(lh, lw, -1)
    elif depth == "F16":
        out = (result_u8.astype(np.float32) / 255.0).clip(0, 1).astype(np.float16)
        result_arr = out.view(np.uint8).reshape(lh, lw, -1)
    elif depth == "F32":
        out = (result_u8.astype(np.float32) / 255.0).clip(0, 1)
        result_arr = out.view(np.uint8).reshape(lh, lw, -1)
    else:
        result_arr = result_u8

    new_layer = create_blank_layer(doc, layer_name, lw, lh)
    write_pixels(new_layer, result_arr, lx, ly, lw, lh, doc)
    doc.setActiveNode(new_layer)
    doc.refreshProjection()
    logger.info(
        f"Removed background (tolerance={tolerance}, contiguous={contiguous}, "
        f"feather={feather}): {pixels_removed} pixels removed"
    )
    return {
        "success": True,
        "message": f"Removed background to layer '{layer_name}' ({pixels_removed} pixels removed)",
        "data": {"layer_name": layer_name, "pixels_removed": pixels_removed},
    }
