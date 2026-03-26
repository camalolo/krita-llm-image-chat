import json
import os

import numpy as np
from krita import Krita, Selection, InfoObject
from PyQt5.QtGui import QColor

from .config import logger, log_exception
from .pixel_ops import (
    get_bpp, get_channels, read_pixels, write_pixels,
    hex_to_rgba, rgba_to_hex, hex_to_managed_color,
    create_blank_layer,
    backup_layer, restore_backup, has_backup,
    perlin_noise_2d, voronoi_2d, fractal_noise_2d,
    adjust_brightness, adjust_contrast, adjust_saturation,
    adjust_hue_shift, adjust_temperature, adjust_gamma,
    color_distance,
    _BLEND_MODE_MAP,
)

BLEND_MODES = [
    "normal", "multiply", "screen", "overlay", "darken",
    "lighten", "color-dodge", "color-burn", "hard-light",
    "soft-light", "difference", "exclusion", "hue",
    "saturation", "color", "luminosity",     "erase",
]

SCHEMA_BLEND_MODES = [
    "normal", "multiply", "screen", "overlay", "soft-light",
    "difference", "color", "luminosity",
]

TOOL_HANDLERS = {}

_last_property_backup = None
_last_selection_backup = None


def _backup_selection(doc):
    global _last_selection_backup
    sel = doc.selection()
    if sel:
        _last_selection_backup = {
            "pixel_data": bytes(sel.pixelData(sel.x(), sel.y(), sel.width(), sel.height())),
            "x": sel.x(),
            "y": sel.y(),
            "width": sel.width(),
            "height": sel.height(),
        }
    else:
        _last_selection_backup = None


def _restore_selection(doc):
    global _last_selection_backup
    if _last_selection_backup is None:
        return False
    backup = _last_selection_backup
    sel = Selection()
    sel.select(backup["x"], backup["y"], backup["width"], backup["height"], 255)
    sel.setPixelData(backup["pixel_data"], backup["x"], backup["y"], backup["width"], backup["height"])
    doc.setSelection(sel)
    _last_selection_backup = None
    doc.refreshProjection()
    logger.info("Restored selection from backup")
    return True


def register_handler(name):
    def decorator(func):
        TOOL_HANDLERS[name] = func
        return func
    return decorator


def _get_document():
    krita = Krita.instance()
    doc = krita.activeDocument()
    if not doc:
        logger.error("No active document found")
        raise Exception("No active document")
    logger.debug(
        f"Got document: {doc.fileName() if doc.fileName() else 'untitled'}, "
        f"size: {doc.width()}x{doc.height()}"
    )
    return doc


def _find_layer(doc, layer_name=None):
    if layer_name:
        logger.debug(f"Finding layer by name: {layer_name}")
        result = _find_layer_recursive(doc.rootNode(), layer_name)
        if result:
            logger.debug(f"Found layer: {layer_name}")
            return result
        logger.error(f"Layer not found: {layer_name}")
        raise Exception(f"Layer not found: {layer_name}")
    layer = doc.activeNode()
    if not layer:
        logger.error("No active layer found")
        raise Exception("No active layer")
    logger.debug(f"Using active layer: {layer.name()}")
    return layer


def _find_layer_recursive(node, layer_name):
    for child in node.childNodes():
        if child.name() == layer_name:
            return child
        if child.type() == "grouplayer":
            result = _find_layer_recursive(child, layer_name)
            if result:
                return result
    return None


# ── 1. image_info ───────────────────────────────────────────────────────────────

@register_handler("image_info")
def handle_image_info(args):
    doc = _get_document()
    root = doc.rootNode()
    layers = []
    for node in root.childNodes():
        layers.append({
            "name": node.name(),
            "type": node.type(),
            "visible": node.visible(),
            "opacity": int(node.opacity() * 100 / 255),
            "blend_mode": node.blendingMode(),
        })
    active = doc.activeNode()
    return {
        "success": True,
        "data": {
            "width": doc.width(),
            "height": doc.height(),
            "resolution": doc.resolution(),
            "color_model": doc.colorModel(),
            "color_depth": doc.colorDepth(),
            "layers": layers,
            "active_layer": active.name() if active else None,
        },
    }


# ── 2. selection ────────────────────────────────────────────────────────────────

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


# ── 3. layer ────────────────────────────────────────────────────────────────────

@register_handler("layer")
def handle_layer(args):
    doc = _get_document()
    action = args.get("action")

    if action == "create":
        name = args.get("name", "New Layer")
        layer_type = args.get("type", "paint")
        opacity = args.get("opacity", 100)
        blend_mode = args.get("blend_mode", "normal")
        root = doc.rootNode()
        if layer_type == "group":
            new_layer = doc.createGroupLayer(name)
        elif layer_type == "vector":
            new_layer = doc.createVectorLayer(name)
        else:
            new_layer = doc.createNode(name, "paintlayer")
        new_layer.setOpacity(int(opacity * 255 / 100))
        krita_blend = _BLEND_MODE_MAP.get(blend_mode, blend_mode)
        new_layer.setBlendingMode(krita_blend)
        root.addChildNode(new_layer, None)
        doc.refreshProjection()
        logger.info(f"Created {layer_type} layer '{name}'")
        return {"success": True, "message": f"Created {layer_type} layer '{name}'", "data": {"layer_name": name}}

    elif action == "delete":
        layer_name = args.get("layer_name")
        layer = _find_layer(doc, layer_name)
        name = layer.name()
        layer.parentNode().removeChildNode(layer)
        doc.refreshProjection()
        logger.info(f"Deleted layer '{name}'")
        return {"success": True, "message": f"Deleted layer '{name}'"}

    elif action == "duplicate":
        layer = _find_layer(doc, args.get("layer_name"))
        new_name = args.get("new_name", f"{layer.name()} copy")
        duplicated = layer.duplicate()
        duplicated.setName(new_name)
        layer.parentNode().addChildNode(duplicated, layer)
        doc.refreshProjection()
        logger.info(f"Duplicated layer '{layer.name()}' as '{new_name}'")
        return {"success": True, "message": f"Duplicated layer as '{new_name}'", "data": {"layer_name": new_name}}

    elif action == "rename":
        layer_name = args.get("layer_name")
        new_name = args.get("new_name")
        if not layer_name or not new_name:
            return {"success": False, "error": "Both layer_name and new_name are required"}
        layer = _find_layer(doc, layer_name)
        old_name = layer.name()
        layer.setName(new_name)
        doc.refreshProjection()
        logger.info(f"Renamed layer '{old_name}' to '{new_name}'")
        return {"success": True, "message": f"Renamed layer '{old_name}' to '{new_name}'"}

    elif action == "set_active":
        layer_name = args.get("layer_name")
        if not layer_name:
            return {"success": False, "error": "layer_name is required"}
        layer = _find_layer(doc, layer_name)
        doc.setActiveNode(layer)
        logger.info(f"Active layer set to '{layer_name}'")
        return {"success": True, "message": f"Active layer set to '{layer_name}'"}

    elif action == "set_properties":
        layer_name = args.get("layer_name")
        layer = _find_layer(doc, layer_name)
        changed = []
        prev_opacity = layer.opacity()
        prev_blend_mode = layer.blendingMode()
        prev_visible = layer.visible()

        opacity = args.get("opacity")
        if opacity is not None:
            layer.setOpacity(int(opacity * 255 / 100))
            changed.append(f"opacity={opacity}%")
        blend_mode = args.get("blend_mode")
        if blend_mode is not None:
            krita_mode = _BLEND_MODE_MAP.get(blend_mode, blend_mode)
            layer.setBlendingMode(krita_mode)
            changed.append(f"blend_mode={blend_mode}")
        visible = args.get("visible")
        if visible is not None:
            layer.setVisible(visible)
            changed.append(f"visible={visible}")
        if not changed:
            return {"success": False, "error": "No properties specified. Provide opacity, blend_mode, or visible."}

        global _last_property_backup
        _last_property_backup = {
            "layer_name": layer.name(),
            "prev_opacity": prev_opacity,
            "prev_blend_mode": prev_blend_mode,
            "prev_visible": prev_visible,
        }
        doc.refreshProjection()
        return {"success": True, "message": f"Updated '{layer.name()}': {', '.join(changed)}"}

    return {"success": False, "error": f"Unknown layer action: {action}"}


# ── 5. layer_stack ──────────────────────────────────────────────────────────────

@register_handler("layer_stack")
def handle_layer_stack(args):
    doc = _get_document()
    action = args.get("action")

    if action == "move":
        layer = _find_layer(doc, args.get("layer_name"))
        parent = layer.parentNode()
        siblings = list(parent.childNodes())
        current_index = siblings.index(layer)
        position = args.get("position")
        direction = args.get("direction", "up")

        if position is not None:
            new_index = max(0, min(int(position), len(siblings) - 1))
        elif direction == "up":
            new_index = min(current_index + 1, len(siblings) - 1)
        elif direction == "down":
            new_index = max(current_index - 1, 0)
        elif direction == "top":
            new_index = len(siblings) - 1
        elif direction == "bottom":
            new_index = 0
        else:
            return {"success": False, "error": f"Unknown direction: {direction}"}

        if new_index == current_index:
            return {"success": True, "message": f"Layer '{layer.name()}' already at requested position"}

        siblings.pop(current_index)
        siblings.insert(new_index, layer)
        parent.setChildNodes(siblings)
        doc.refreshProjection()
        logger.info(f"Moved layer '{layer.name()}' to index {new_index}")
        return {"success": True, "message": f"Moved layer '{layer.name()}' to index {new_index}"}

    elif action == "merge_down":
        layer = _find_layer(doc, args.get("layer_name"))
        parent = layer.parentNode()
        siblings = list(parent.childNodes())
        idx = siblings.index(layer)
        if idx == 0:
            return {"success": False, "error": "No layer below to merge into"}
        below = siblings[idx - 1]
        layer_name = layer.name()
        below_name = below.name()
        doc.setActiveNode(layer)
        krita_action = Krita.instance().action("merge_down")
        if krita_action:
            krita_action.trigger()
            doc.refreshProjection()
            logger.info(f"Merged '{layer_name}' down into '{below_name}'")
            return {"success": True, "message": f"Merged '{layer_name}' down into '{below_name}'"}
        return {"success": False, "error": "Merge down action not available"}

    elif action == "flatten":
        krita_action = Krita.instance().action("flatten_image")
        if krita_action:
            krita_action.trigger()
            doc.refreshProjection()
            logger.info("Flattened all visible layers")
            return {"success": True, "message": "Flattened all visible layers"}
        return {"success": False, "error": "Flatten image action not available"}

    elif action == "extract_selection":
        selection = doc.selection()
        if not selection:
            return {"success": False, "error": "No selection exists. Create a selection first."}
        source_name = args.get("source_layer_name")
        new_name = args.get("new_layer_name", "Copied Selection")
        source = _find_layer(doc, source_name)
        x, y = selection.x(), selection.y()
        w, h = selection.width(), selection.height()
        pixel_data = source.pixelData(x, y, w, h)
        new_layer = doc.createNode(new_name, "paintlayer")
        new_layer.setPixelData(pixel_data, x, y, w, h)
        doc.rootNode().addChildNode(new_layer, source)
        doc.setActiveNode(new_layer)
        doc.refreshProjection()
        logger.info(f"Extracted selection to layer '{new_name}'")
        return {
            "success": True,
            "message": f"Copied selection region to new layer '{new_name}'",
            "data": {"layer_name": new_name, "x": x, "y": y, "width": w, "height": h},
        }

    return {"success": False, "error": f"Unknown layer_stack action: {action}"}


# ── 6. transform ────────────────────────────────────────────────────────────────

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


# ── 7. fill ─────────────────────────────────────────────────────────────────────

@register_handler("fill")
def handle_fill(args):
    doc = _get_document()
    fill_type = args.get("type", "foreground")
    color_hex = args.get("color")
    krita = Krita.instance()
    view = krita.activeWindow().activeView() if krita.activeWindow() else None
    if not view:
        return {"success": False, "error": "No active window/view"}

    if color_hex:
        color = hex_to_managed_color(color_hex, doc)
        if fill_type == "foreground":
            view.setForeGroundColor(color)
        elif fill_type == "background":
            view.setBackGroundColor(color)

    if fill_type == "foreground":
        action = Krita.instance().action("fill_selection_foreground_color")
    elif fill_type == "background":
        action = Krita.instance().action("fill_selection_background_color")
    else:
        action = Krita.instance().action("fill_selection_foreground_color")

    if action:
        action.trigger()
        doc.refreshProjection()
        logger.info(f"Filled with {fill_type}" + (f" color={color_hex}" if color_hex else ""))
        return {"success": True, "message": f"Filled with {fill_type}" + (f" color={color_hex}" if color_hex else "")}
    return {"success": False, "error": "Fill action not available"}


# ── 8. apply_effect ─────────────────────────────────────────────────────────────

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


# ── 9. export ───────────────────────────────────────────────────────────────────

@register_handler("export")
def handle_export(args):
    doc = _get_document()
    action = args.get("action", "save")

    if action == "save":
        export_format = args.get("format", "png")
        if export_format == "jpg":
            export_format = "jpeg"
        override_folder = args.get("folder")

        if override_folder:
            folder = override_folder
        elif doc.fileName():
            folder = os.path.dirname(doc.fileName())
            if not folder:
                folder = os.path.join(os.path.expanduser("~"), "Desktop")
        else:
            folder = os.path.join(os.path.expanduser("~"), "Desktop")

        os.makedirs(folder, exist_ok=True)
        base_name = os.path.splitext(doc.name())[0]
        if not base_name:
            base_name = "Untitled"

        current_path = os.path.normpath(doc.fileName()) if doc.fileName() else ""
        kra_path = None
        export_path = None

        for i in range(1000):
            suffix = f"_{i:03d}" if i > 0 else ""
            candidate_kra = os.path.join(folder, f"{base_name}{suffix}.kra")
            candidate_export = os.path.join(folder, f"{base_name}{suffix}.{export_format}")
            if (not os.path.exists(candidate_kra)
                    and not os.path.exists(candidate_export)
                    and os.path.normpath(candidate_kra) != current_path
                    and os.path.normpath(candidate_export) != current_path):
                kra_path = candidate_kra
                export_path = candidate_export
                break

        if not kra_path:
            return {"success": False, "error": "Could not find a non-colliding filename after 1000 attempts"}

        save_ok = doc.saveAs(kra_path)
        if not save_ok:
            return {"success": False, "error": f"Failed to save document to '{kra_path}'"}

        info = InfoObject()
        if export_format == "jpeg":
            info.setProperty("quality", 90)
        doc.setBatchmode(True)
        try:
            export_ok = doc.exportImage(export_path, info)
        finally:
            doc.setBatchmode(False)

        if not export_ok:
            return {"success": False, "error": f"Saved .kra but failed to export to '{export_path}'"}

        logger.info(f"Saved '{kra_path}' and exported '{export_path}'")
        return {"success": True, "message": f"Saved '{kra_path}' and exported '{export_path}'",
                "data": {"kra_path": kra_path, "export_path": export_path}}

    elif action == "export":
        path = args.get("path")
        file_format = args.get("format", "png")
        overwrite = args.get("overwrite", False)
        if not path:
            return {"success": False, "error": "path is required"}
        if file_format == "jpg":
            file_format = "jpeg"
        base, ext = os.path.splitext(path)
        if not ext:
            path = f"{path}.{file_format}"
        current_path = doc.fileName()
        if current_path and os.path.normpath(path) == os.path.normpath(current_path):
            return {"success": False, "error": "Cannot overwrite the currently open document."}
        if os.path.exists(path) and not overwrite:
            return {"success": False, "error": "File already exists (set overwrite=true to replace)"}

        info = InfoObject()
        if file_format == "jpeg":
            info.setProperty("quality", 90)
        doc.setBatchmode(True)
        try:
            success = doc.exportImage(path, info)
        finally:
            doc.setBatchmode(False)

        if success:
            logger.info(f"Exported to '{path}'")
            return {"success": True, "message": f"Exported to '{path}'"}
        return {"success": False, "error": f"Failed to export to '{path}'"}

    elif action == "split":
        regions = args.get("regions")
        overwrite = args.get("overwrite", False)
        if not regions or not isinstance(regions, list):
            return {"success": False, "error": "regions is required and must be a list of {x, y, w, h, path} objects"}

        current_path = os.path.normpath(doc.fileName()) if doc.fileName() else ""
        results = []

        doc.setBatchmode(True)
        try:
            for i, region in enumerate(regions):
                rx = region.get("x")
                ry = region.get("y")
                rw = region.get("w")
                rh = region.get("h")
                rpath = region.get("path")

                if rx is None or ry is None or rw is None or rh is None or not rpath:
                    results.append({"index": i, "success": False, "error": "Missing required field(s)"})
                    continue

                _, ext = os.path.splitext(rpath)
                if not ext:
                    rpath = f"{rpath}.png"
                    ext = ".png"
                file_format = ext.lstrip('.').lower()
                if file_format == "jpg":
                    file_format = "jpeg"

                if os.path.exists(rpath) and not overwrite:
                    results.append({"index": i, "success": False, "path": rpath,
                                    "error": "File already exists (set overwrite=true)"})
                    continue

                if current_path and os.path.normpath(rpath) == current_path:
                    results.append({"index": i, "success": False, "path": rpath,
                                    "error": "Cannot overwrite the currently open document"})
                    continue

                export_ok = False
                selection = Selection()
                selection.select(int(rx), int(ry), int(rw), int(rh), 255)
                doc.setSelection(selection)
                try:
                    crop_action = Krita.instance().action("resizeimagetoselection")
                    if not crop_action:
                        results.append({"index": i, "success": False, "error": "Trim-to-selection action not available"})
                        continue
                    crop_action.trigger()
                    doc.refreshProjection()
                    os.makedirs(os.path.dirname(os.path.abspath(rpath)), exist_ok=True)
                    info = InfoObject()
                    if file_format == "jpeg":
                        info.setProperty("quality", 90)
                    try:
                        export_ok = doc.exportImage(rpath, info)
                    except Exception as e:
                        export_ok = False
                        logger.error(f"Exception during export of region {i}: {e}")
                finally:
                    undo_action = Krita.instance().action("edit_undo")
                    if undo_action and undo_action.isEnabled():
                        undo_action.trigger()
                        doc.refreshProjection()
                    else:
                        logger.warning(f"Could not undo after region {i}")
                    doc.setSelection(None)

                if export_ok:
                    results.append({"index": i, "success": True, "path": rpath})
                    logger.info(f"Exported region {i} to '{rpath}'")
                else:
                    results.append({"index": i, "success": False, "path": rpath,
                                    "error": f"Export to '{rpath}' failed"})
        finally:
            doc.setBatchmode(False)

        success_count = sum(1 for r in results if r.get("success"))
        fail_count = len(results) - success_count
        if success_count == len(results):
            return {"success": True, "message": f"Exported all {len(results)} regions",
                    "data": {"results": results}}
        elif success_count > 0:
            return {"success": True,
                    "message": f"Exported {success_count}/{len(results)} regions ({fail_count} failed)",
                    "data": {"results": results}}
        return {"success": False, "error": f"All {len(results)} regions failed to export",
                "data": {"results": results}}

    return {"success": False, "error": f"Unknown export action: {action}"}


# ── 10. document ────────────────────────────────────────────────────────────────

@register_handler("document")
def handle_document(args):
    action = args.get("action")

    if action == "new":
        krita = Krita.instance()
        width = args.get("width", 1920)
        height = args.get("height", 1080)
        name = args.get("name", "Untitled")
        resolution = args.get("resolution", 72.0)
        if width < 1 or height < 1:
            return {"success": False, "error": "Width and height must be at least 1"}
        doc = krita.createDocument(width, height, name, "RGBA", "U8", "sRGB-elle-v2-srgbtrc.icc", resolution)
        if not doc:
            return {"success": False, "error": "Failed to create new document"}
        window = krita.activeWindow()
        if window:
            window.addView(doc)
        logger.info(f"Created document '{name}' ({width}x{height})")
        return {"success": True, "message": f"Created document '{name}' ({width}x{height})",
                "data": {"width": width, "height": height, "name": name}}

    elif action == "crop":
        doc = _get_document()
        x = args.get("x")
        y = args.get("y")
        w = args.get("w")
        h = args.get("h")
        if x is not None and y is not None and w is not None and h is not None:
            selection = Selection()
            selection.select(int(x), int(y), int(w), int(h), 255)
            doc.setSelection(selection)
        else:
            selection = doc.selection()
            if not selection:
                return {"success": False, "error": "No bounds specified and no selection exists"}
        krita_action = Krita.instance().action("resizeimagetoselection")
        if krita_action:
            krita_action.trigger()
            doc.refreshProjection()
            logger.info("Cropped document")
            return {"success": True, "message": "Cropped document to selection"}
        return {"success": False, "error": "Trim-to-selection action not available"}

    return {"success": False, "error": f"Unknown document action: {action}"}


# ── 11. undo ────────────────────────────────────────────────────────────────────

@register_handler("undo")
def handle_undo(args):
    global _last_property_backup
    doc = _get_document()
    layer = doc.activeNode()

    if layer:
        layer_name = layer.name()
        if restore_backup(layer_name, layer, doc):
            doc.refreshProjection()
            logger.info(f"Reverted filter on layer '{layer_name}' from backup")
            return {"success": True, "message": f"Reverted filter on layer '{layer_name}'"}

    if _last_property_backup is not None:
        backup = _last_property_backup
        target = _find_layer_recursive(doc.rootNode(), backup["layer_name"])
        if target:
            target.setOpacity(backup["prev_opacity"])
            target.setBlendingMode(backup["prev_blend_mode"])
            target.setVisible(backup["prev_visible"])
            _last_property_backup = None
            doc.refreshProjection()
            logger.info(f"Reverted property changes on '{backup['layer_name']}'")
            return {"success": True, "message": f"Reverted property changes on '{backup['layer_name']}'"}

    if _restore_selection(doc):
        return {"success": True, "message": "Restored selection from backup"}

    krita = Krita.instance()
    action = krita.action("edit_undo")
    if not action:
        return {"success": False, "error": "Undo action not available"}
    if not action.isEnabled():
        return {"success": False, "error": "Nothing to undo"}
    action.trigger()
    logger.info("Performed Krita undo")
    return {"success": True, "message": "Undo performed"}


# ── 12. redo ────────────────────────────────────────────────────────────────────

@register_handler("redo")
def handle_redo(args):
    krita = Krita.instance()
    action = krita.action("edit_redo")
    if not action:
        return {"success": False, "error": "Redo action not available"}
    if not action.isEnabled():
        return {"success": False, "error": "Nothing to redo"}
    action.trigger()
    logger.info("Performed redo")
    return {"success": True, "message": "Redo performed"}


# ── ARTISTIC TOOL HANDLERS ──────────────────────────────────────────────────────
# All artistic tools are non-destructive: they create a new layer with the result.


def _read_active_for_art(args):
    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        raise Exception("No active layer")
    arr, x, y, w, h = read_pixels(layer, doc)
    if arr.size == 0:
        return {"success": False, "error": f"Active layer '{layer.name()}' has no pixel data (empty bounds: {w}x{h}). Cannot perform operation."}
    return doc, layer, arr, x, y, w, h


# ── 13. color_grade ─────────────────────────────────────────────────────────────

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


# ── 14. procedural_texture ──────────────────────────────────────────────────────

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


# ── 15. adjust ──────────────────────────────────────────────────────────────────

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


# ── 16. extract_subject ─────────────────────────────────────────────────────────

@register_handler("extract_subject")
def handle_extract_subject(args):
    result = _read_active_for_art(args)
    if isinstance(result, dict):
        return result
    doc, layer, arr, x, y, w, h = result
    target_hex = args.get("target_color")
    threshold = args.get("threshold", 30)
    softness = args.get("softness", 20)
    new_name = args.get("layer_name", "Extracted Subject")

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
    logger.info(f"Extracted subject (threshold={threshold}, softness={softness})")
    return {"success": True, "message": f"Extracted subject to layer '{new_name}'",
            "data": {"layer_name": new_name}}


# ── 17. apply_lut ───────────────────────────────────────────────────────────────

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


# ── execute_tool ────────────────────────────────────────────────────────────────

def execute_tool(tool_name, args):
    logger.debug(f"execute_tool called: {tool_name}, args: {args}")
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        logger.error(f"Unknown tool: {tool_name}. Available: {list(TOOL_HANDLERS.keys())}")
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    try:
        logger.debug(f"Calling handler for {tool_name}")
        result = handler(args if args else {})
        logger.debug(f"Handler returned: {result}")
        if not isinstance(result, dict):
            logger.warning(f"Handler for {tool_name} returned non-dict: {type(result).__name__}: {result}")
            result = {"success": True, "message": str(result)} if result else {"success": True}
        return result
    except Exception as e:
        log_exception(e, f"execute_tool({tool_name})")
        return {"success": False, "error": str(e)}

# ── Tool categories for dynamic loading ──────────────────────────────────────────

CORE_TOOLS = ["image_info", "undo", "redo"]
CREATIVE_TOOLS = [
    "color_grade", "procedural_texture", "adjust",
    "extract_subject", "apply_lut", "apply_effect", "fill",
]
STRUCTURAL_TOOLS = [
    "layer", "layer_stack", "transform", "selection",
    "document", "export",
]

_CREATIVE_KEYWORDS = {
    "color", "grade", "texture", "noise", "blur", "sharpen", "effect",
    "filter", "warm", "cool", "vintage", "cinematic", "dramatic", "faded",
    "bright", "contrast", "saturat", "hue", "temperature", "vibrance",
    "gamma", "extract", "subject", "background", "adjust", "darken",
    "lighten", "posterize", "threshold", "desaturat", "invert", "emboss",
    "pixelat", "oil", "wave", "edge", "marble", "perlin", "voronoi",
    "checker", "dots", "cloud", "wood", "lut", "gradient",
}
_STRUCTURAL_KEYWORDS = {
    "layer", "group", "selection", "select", "crop", "resize", "scale",
    "rotate", "flip", "transform", "export", "save", "document", "merge",
    "flatten", "move", "duplicate", "delete", "rename", "new", "opacity",
    "blend", "visible", "hide", "show",
}


def classify_tools(user_message):
    """Classify user message to determine which tool subset to send.
    
    Returns:
        "creative" — if only creative keywords found
        "structural" — if only structural keywords found
        None — if ambiguous or no keywords (sends all tools)
    """
    if not user_message:
        return None
    lower = user_message.lower()
    has_creative = any(kw in lower for kw in _CREATIVE_KEYWORDS)
    has_structural = any(kw in lower for kw in _STRUCTURAL_KEYWORDS)
    if has_creative and not has_structural:
        return "creative"
    if has_structural and not has_creative:
        return "structural"
    return None


# ── generate_tools ──────────────────────────────────────────────────────────────

_cached_tools = None
_cached_tools_creative = None
_cached_tools_structural = None


def generate_tools(context=None):
    if context == "creative":
        global _cached_tools_creative
        if _cached_tools_creative is not None:
            return _cached_tools_creative
    elif context == "structural":
        global _cached_tools_structural
        if _cached_tools_structural is not None:
            return _cached_tools_structural
    else:
        global _cached_tools
        if _cached_tools is not None:
            return _cached_tools

    _anchor_options = [
        "center", "top-left", "top", "top-right",
        "left", "right", "bottom-left", "bottom", "bottom-right",
    ]
    _move_directions = ["up", "down", "top", "bottom"]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "image_info",
                "description": "Get document info: dimensions, resolution, color model, layers, active layer. Call this first.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "selection",
                "description": (
                    "Manage selections. Actions: 'create' — make a new selection (type='rect' with x,y,w,h or type='all'); "
                    "'modify' — alter existing selection (modify_action: invert, feather, grow, shrink, smooth; "
                    "value sets the modifier amount); 'clear' — remove selection; 'info' — get selection bounds."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create", "modify", "clear", "info"],
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
        },
        {
            "type": "function",
            "function": {
                "name": "layer",
                "description": (
                    "Layer management. Actions: 'create' — add a new layer (name, type, opacity, blend_mode); "
                    "'delete' — remove a layer; 'duplicate' — copy a layer; "
                    "'rename' — rename a layer (layer_name + new_name required); "
                    "'set_active' — set the active layer; "
                    "'set_properties' — set opacity, blend_mode, and/or visibility on a layer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create", "delete", "duplicate", "rename", "set_active", "set_properties"],
                            "description": "Layer action to perform",
                        },
                        "name": {"type": "string", "description": "Layer name for create/rename"},
                        "type": {
                            "type": "string",
                            "enum": ["paint", "group", "vector"],
                            "description": "Layer type for create action (default 'paint')",
                        },
                        "opacity": {"type": "number", "description": "Opacity 0-100 (for create and set_properties)", "minimum": 0, "maximum": 100},
                        "blend_mode": {
                            "type": "string",
                            "enum": SCHEMA_BLEND_MODES,
                            "description": "Blend mode (for create and set_properties). Also supports: darken, lighten, color-dodge, color-burn, hard-light, exclusion, hue, saturation, erase",
                        },
                        "layer_name": {"type": "string", "description": "Target layer name for delete/duplicate/rename/set_active"},
                        "new_name": {"type": "string", "description": "New name for duplicate/rename actions"},
                        "visible": {"type": "boolean", "description": "Layer visibility (for set_properties action)"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "layer_stack",
                "description": (
                    "Layer ordering and merging. Actions: 'move' — reorder a layer (direction or position); "
                    "'merge_down' — merge active/target layer into the one below; "
                    "'flatten' — merge all visible layers; "
                    "'extract_selection' — copy selection region to a new layer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["move", "merge_down", "flatten", "extract_selection"],
                            "description": "Layer stack action to perform",
                        },
                        "layer_name": {"type": "string", "description": "Target layer name"},
                        "direction": {
                            "type": "string",
                            "enum": _move_directions,
                            "description": "Move direction for move action",
                        },
                        "position": {"type": "integer", "description": "Absolute index for move action"},
                        "source_layer_name": {"type": "string", "description": "Source layer for extract_selection"},
                        "new_layer_name": {"type": "string", "description": "New layer name for extract_selection"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
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
                            "enum": _anchor_options,
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
        },
        {
            "type": "function",
            "function": {
                "name": "fill",
                "description": "Fill the active layer or selection with a color. Optionally set the color first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "color": {
                            "type": "string",
                            "description": "Hex color to fill with, e.g. '#FF0000'",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["foreground", "background"],
                            "description": "Fill source (default 'foreground')",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
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
        },
        {
            "type": "function",
            "function": {
                "name": "export",
                "description": (
                    "Save and export documents. Actions: 'save' — save .kra + export to PNG/JPG (optionally specify folder); "
                    "'export' — export to a specific path (path required); "
                    "'split' — export multiple rectangular regions as separate files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["save", "export", "split"],
                            "description": "Export action to perform",
                        },
                        "path": {"type": "string", "description": "Output file path (required for export action)"},
                        "format": {
                            "type": "string",
                            "enum": ["png", "jpg"],
                            "description": "Output format (default 'png')",
                        },
                        "folder": {"type": "string", "description": "Output folder for save action"},
                        "overwrite": {"type": "boolean", "description": "Overwrite existing files (default false)"},
                        "regions": {
                            "type": "array",
                            "description": "List of region objects for split action, each with x, y, w, h, path",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "integer", "minimum": 0},
                                    "y": {"type": "integer", "minimum": 0},
                                    "w": {"type": "integer", "minimum": 0},
                                    "h": {"type": "integer", "minimum": 0},
                                    "path": {"type": "string"},
                                },
                                "required": ["x", "y", "w", "h", "path"],
                            },
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "document",
                "description": (
                    "Document operations. Actions: 'new' — create a new document (width, height, name, resolution); "
                    "'crop' — crop document to a rectangle (x, y, w, h) or to the current selection."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["new", "crop"],
                            "description": "Document action to perform",
                        },
                        "width": {"type": "integer", "description": "Width in pixels (for new, default 1920)", "minimum": 1},
                        "height": {"type": "integer", "description": "Height in pixels (for new, default 1080)", "minimum": 1},
                        "name": {"type": "string", "description": "Document name for new action"},
                        "resolution": {"type": "number", "description": "Resolution in PPI for new action (default 72)", "minimum": 1},
                        "x": {"type": "number", "description": "Crop left edge (pixels)"},
                        "y": {"type": "number", "description": "Crop top edge (pixels)"},
                        "w": {"type": "number", "description": "Crop width (pixels)"},
                        "h": {"type": "number", "description": "Crop height (pixels)"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "undo",
                "description": "Undo the last operation. Checks filter backup first, then falls back to Krita undo.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "redo",
                "description": "Redo the last undone operation.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
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
        },
        {
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
        },
        {
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
        },
        {
            "type": "function",
            "function": {
                "name": "extract_subject",
                "description": (
                    "Extract a subject by removing a background color. Non-destructive (creates new layer). "
                    "When target_color is omitted, auto-detects the background from image corners."
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
        },
        {
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
        },
    ]

    _cached_tools = tools

    creative_names = set(CORE_TOOLS + CREATIVE_TOOLS)
    structural_names = set(CORE_TOOLS + STRUCTURAL_TOOLS)

    _cached_tools_creative = [t for t in tools
                              if t["function"]["name"] in creative_names]
    _cached_tools_structural = [t for t in tools
                                if t["function"]["name"] in structural_names]

    if context == "creative":
        return _cached_tools_creative
    elif context == "structural":
        return _cached_tools_structural
    return tools
