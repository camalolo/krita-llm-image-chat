"""Apply visual effects (blur, sharpen, noise, invert, threshold, etc.) to the active layer."""

import numpy as np
from krita import Krita
from PyQt5.QtGui import QColor
from ._registry import register_handler, TOOL_SCHEMAS, _get_document
from ..pixel_ops import read_pixels, write_pixels, backup_layer, adjust_saturation
from ..config import logger

_EFFECT_NAME_MAP = {
    "blur": ["blur"],
    "sharpen": ["sharpen"],
    "noise": ["noise", "add noise", "add noise..."],
    "edge_detect": ["edge detection"],
    "emboss": ["emboss"],
    "pixelate": ["pixelize", "pixelate"],
    "brightness_contrast": ["brightness/contrast"],
    "hue_saturation": ["hue/saturation"],
    "color_balance": ["color balance"],
    "invert": [],
    "posterize": ["posterize"],
    "threshold": [],
    "oil_paint": ["oil paint", "oilpaint"],
    "color_to_alpha": ["color to alpha", "colortoalpha"],
    "gaussian_blur": ["gaussian blur"],
    "motion_blur": ["motion blur"],
    "wave": ["wave"],
    "desaturate": [],
    "unsharp_mask": ["unsharp mask"],
    "lens_blur": ["lens blur"],
    "gaussian_high_pass": ["gaussian high pass"],
    "height_to_normal": ["height to normal map"],
    "auto_contrast": ["auto contrast"],
    "mean_removal": ["mean removal"],
    "color_transfer": ["color transfer"],
    "gradient_map": ["gradient map"],
}

_EFFECT_INTENSITY_PROPS = {
    "blur": ["radius", "strength"],
    "sharpen": ["sharpness", "strength"],
    "noise": ["amount", "intensity"],
    "gaussian_blur": ["radius", "strength"],
    "pixelate": ["pixelSize", "pixel size", "size"],
    "edge_detect": ["strength"],
    "emboss": ["strength"],
    "oil_paint": ["brush radius", "radius", "size"],
    "wave": ["amplitude", "wavelength"],
    "motion_blur": ["distance", "strength", "radius"],
    "posterize": ["levels", "level"],
    "brightness_contrast": ["brightness", "contrast"],
    "hue_saturation": ["saturation", "hue"],
    "color_balance": ["strength", "contrast"],
    "unsharp_mask": ["half-size", "amount", "strength"],
    "lens_blur": ["radius", "brightness", "threshold"],
    "gaussian_high_pass": ["radius", "strength"],
    "height_to_normal": ["radius", "strength"],
    "mean_removal": ["radius", "strength"],
    "gradient_map": ["opacity", "strength"],
}

_effect_filter_map = None


def _build_effect_filter_map():
    global _effect_filter_map
    if _effect_filter_map is not None:
        return _effect_filter_map

    _effect_filter_map = {}
    available = [str(f).lower() for f in list(Krita.instance().filters())]
    for effect, candidates in _EFFECT_NAME_MAP.items():
        if not candidates:
            continue
        for candidate in candidates:
            if candidate in available:
                _effect_filter_map[effect] = candidate
                break

    logger.debug(f"Built effect filter map: {_effect_filter_map}")
    return _effect_filter_map

TOOL_SCHEMAS["apply_effect"] = {
    "type": "function",
    "function": {
        "name": "apply_effect",
        "description": (
            "Apply a visual effect to the active layer. intensity (0-100) controls effect strength. "
            "target_color and threshold are used only with color_to_alpha. "
            "Destructive — applies directly to the active layer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "effect": {
                    "type": "string",
                    "enum": [
                        "auto_contrast", "blur", "brightness_contrast",
                        "color_balance", "color_to_alpha", "color_transfer",
                        "desaturate", "edge_detect", "emboss", "gaussian_blur",
                        "gaussian_high_pass", "gradient_map", "height_to_normal",
                        "hue_saturation", "invert", "lens_blur", "mean_removal",
                        "motion_blur", "noise", "oil_paint", "pixelate",
                        "posterize", "sharpen", "threshold", "unsharp_mask",
                        "wave",
                    ],
                    "description": "Effect to apply",
                },
                "intensity": {"type": "number", "description": "Effect strength 0-100 (default 50)", "minimum": 0, "maximum": 100},
                "target_color": {
                    "type": "string",
                    "description": "Hex color for color_to_alpha effect",
                },
                "threshold": {
                    "type": "integer",
                    "description": "Threshold value for color_to_alpha (0-255)",
                },
            },
            "required": ["effect"],
        },
    },
}

@register_handler("apply_effect")
def handle_apply_effect(args):
    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        return {"success": False, "error": "No active layer"}

    effect = args.get("effect")
    if not effect:
        return {"success": False, "error": "effect is required"}

    intensity = args.get("intensity", 50)
    target_color = args.get("target_color")
    threshold = args.get("threshold")
    w, h = doc.width(), doc.height()

    if effect == "invert":
        arr, x, y, lw, lh = read_pixels(layer, doc)
        if arr.shape[2] >= 4:
            arr[:, :, :3] = 255 - arr[:, :, :3]
        else:
            arr = 255 - arr
        backup_layer(layer, doc)
        write_pixels(layer, arr, x, y, lw, lh, doc)
        doc.refreshProjection()
        logger.info("Applied invert effect")
        return {"success": True, "message": "Applied invert effect"}

    if effect == "threshold":
        arr, x, y, lw, lh = read_pixels(layer, doc)
        gray = (0.299 * arr[:, :, 0].astype(np.float64)
                + 0.587 * arr[:, :, 1].astype(np.float64)
                + 0.114 * arr[:, :, 2].astype(np.float64))
        thresh_val = int(intensity / 100.0 * 255)
        mask = (gray >= thresh_val).astype(np.uint8) * 255
        if arr.shape[2] >= 3:
            arr[:, :, 0] = mask
            arr[:, :, 1] = mask
            arr[:, :, 2] = mask
        else:
            arr = mask[:, :, np.newaxis]
        backup_layer(layer, doc)
        write_pixels(layer, arr, x, y, lw, lh, doc)
        doc.refreshProjection()
        logger.info(f"Applied threshold effect (threshold={thresh_val})")
        return {"success": True, "message": f"Applied threshold effect (threshold={thresh_val})"}

    if effect == "desaturate":
        arr, x, y, lw, lh = read_pixels(layer, doc)
        arr = adjust_saturation(arr, -100)
        backup_layer(layer, doc)
        write_pixels(layer, arr, x, y, lw, lh, doc)
        doc.refreshProjection()
        logger.info("Applied desaturate effect")
        return {"success": True, "message": "Applied desaturate effect"}

    fmap = _build_effect_filter_map()
    krita_filter_name = fmap.get(effect)
    if not krita_filter_name:
        return {"success": False, "error": f"No Krita filter found for effect '{effect}'"}

    filter_obj = Krita.instance().filter(krita_filter_name)
    if not filter_obj:
        return {"success": False, "error": f"Could not create filter for '{effect}'"}

    config = filter_obj.configuration()
    if config:
        set_any = False
        parts = []

        intensity_prop_names = _EFFECT_INTENSITY_PROPS.get(effect, [])
        for prop_candidate in intensity_prop_names:
            for prop_obj in config.properties():
                if prop_candidate.lower() in str(prop_obj).lower():
                    try:
                        test_val = config.property(prop_obj)
                        if isinstance(test_val, float):
                            normalized = intensity / 100.0
                        elif isinstance(test_val, int):
                            normalized = int(intensity / 100.0 * 255)
                        else:
                            normalized = intensity
                        config.setProperty(prop_obj, normalized)
                        set_any = True
                        logger.debug(f"Set property {prop_obj} to {normalized}")
                    except Exception as e:
                        logger.warning(f"Failed to set property {prop_obj}: {e}")
                    break

        if target_color:
            for prop_obj in config.properties():
                pname = str(prop_obj).lower()
                if "color" in pname and "target" in pname:
                    try:
                        color = QColor(target_color)
                        if color.isValid():
                            config.setProperty(prop_obj, color)
                            set_any = True
                            parts.append(f"target_color={target_color}")
                    except Exception as e:
                        logger.warning(f"Failed to set targetcolor: {e}")
                    break

        if threshold is not None:
            for prop_obj in config.properties():
                pname = str(prop_obj).lower()
                if "threshold" in pname:
                    try:
                        config.setProperty(prop_obj, int(threshold))
                        set_any = True
                        parts.append(f"threshold={threshold}")
                    except Exception as e:
                        logger.warning(f"Failed to set threshold: {e}")
                    break

        if not set_any:
            logger.debug(f"No adjustable properties on filter '{krita_filter_name}', applying with defaults")
        filter_obj.setConfiguration(config)

    backup_layer(layer, doc)
    filter_obj.apply(layer, 0, 0, w, h)
    doc.refreshProjection()
    msg = f"Applied '{effect}'"
    if parts:
        msg += f" ({', '.join(parts)})"
    logger.info(msg)
    return {"success": True, "message": msg}
