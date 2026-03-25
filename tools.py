from krita import Krita, Selection, InfoObject, ManagedColor
from .config import logger, log_exception
import os

BLEND_MODES = ["normal", "multiply", "screen", "overlay", "darken",
               "lighten", "color-dodge", "color-burn", "hard-light",
               "soft-light", "difference", "exclusion", "hue",
               "saturation", "color", "luminosity", "erase"]

BLEND_MODE_MAP = {
    "normal": "normal",
    "multiply": "multiply",
    "screen": "screen",
    "overlay": "overlay",
    "darken": "darken",
    "lighten": "lighten",
    "color-dodge": "color dodge",
    "color-burn": "color burn",
    "hard-light": "hard light",
    "soft-light": "soft light",
    "difference": "difference",
    "exclusion": "exclusion",
    "hue": "hue",
    "saturation": "saturation",
    "color": "color",
    "luminosity": "luminosity",
    "erase": "erase"
}

TOOL_HANDLERS = {}

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
    logger.debug(f"Got document: {doc.fileName() if doc.fileName() else 'untitled'}, size: {doc.width()}x{doc.height()}")
    return doc

def _find_layer(doc, layer_name=None):
    """Find a layer by name, searching recursively inside group layers."""
    if layer_name:
        logger.debug(f"Finding layer by name: {layer_name}")
        root = doc.rootNode()
        result = _find_layer_recursive(root, layer_name)
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
    """Recursively search for a layer by name within a node's children."""
    for child in node.childNodes():
        if child.name() == layer_name:
            return child
        if child.type() == "grouplayer":
            result = _find_layer_recursive(child, layer_name)
            if result:
                return result
    return None

def _opacity_to_krita(opacity):
    return int(opacity * 255 / 100)

def _opacity_from_krita(opacity):
    return int(opacity * 100 / 255)

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
            "opacity": _opacity_from_krita(node.opacity()),
            "blend_mode": node.blendingMode()
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
            "active_layer": active.name() if active else None
        }
    }

@register_handler("apply_filter")
def handle_apply_filter(args):
    logger.debug(f"handle_apply_filter called with args: {args}")
    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        logger.error("No active layer in apply_filter")
        return {"success": False, "error": "No active layer"}
    filter_name = args.get("name")
    intensity = args.get("intensity", 50)
    logger.debug(f"Filter name: {filter_name}, intensity: {intensity}")
    
    krita = Krita.instance()
    available_filters = list(krita.filters())
    logger.debug(f"Available filters count: {len(available_filters)}")
    
    if filter_name not in available_filters:
        logger.error(f"Filter not found: {filter_name}")
        return {"success": False, "error": f"Unknown filter: {filter_name}. Available: {available_filters[:10]}..."}
    filter_obj = krita.filter(filter_name)
    if filter_obj:
        logger.debug(f"Created filter object for {filter_name}")
        config = filter_obj.configuration()
        if config:
            logger.debug(f"Filter has configuration, properties: {[p.name for p in config.properties()]}")
            set_any = False
            for prop in config.properties():
                prop_name = prop.name.lower()
                if any(x in prop_name for x in ["radius", "strength", "intensity", "amount", "level"]):
                    logger.debug(f"Found target property {prop.name}, type hint: {type(prop)}, min: {prop.min}, max: {prop.max}")
                    try:
                        prop_min = prop.min
                        prop_max = prop.max
                        if prop_min is not None and prop_max is not None and prop_max > prop_min:
                            normalized = prop_min + (intensity / 100.0) * (prop_max - prop_min)
                        else:
                            try:
                                test_val = config.property(prop.name)
                                if isinstance(test_val, float):
                                    normalized = intensity / 100.0
                                else:
                                    normalized = int(intensity / 100.0 * 255)
                            except Exception:
                                normalized = intensity
                        config.setProperty(prop.name, normalized)
                        set_any = True
                        logger.debug(f"Set property {prop.name} to {normalized} (from intensity {intensity})")
                    except Exception as e:
                        logger.warning(f"Failed to set property {prop.name}: {e}")
                    break
            if not set_any:
                logger.warning(f"No suitable property found on filter '{filter_name}' to set intensity")
                return {"success": False, "error": f"Filter '{filter_name}' has no adjustable intensity property"}
            filter_obj.setConfiguration(config)
        logger.debug(f"Applying filter to layer {layer.name()}")
        filter_obj.apply(layer, 0, 0, doc.width(), doc.height())
        doc.refreshProjection()
        logger.info(f"Successfully applied filter '{filter_name}' with intensity {intensity}")
        return {"success": True, "message": f"Applied filter '{filter_name}' with intensity {intensity}"}
    logger.error(f"Could not create filter: {filter_name}")
    return {"success": False, "error": f"Could not create filter: {filter_name}"}

@register_handler("layer_create")
def handle_layer_create(args):
    doc = _get_document()
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
    new_layer.setOpacity(_opacity_to_krita(opacity))
    krita_blend = BLEND_MODE_MAP.get(blend_mode, blend_mode)
    new_layer.setBlendingMode(krita_blend)
    root.addChildNode(new_layer, None)
    doc.refreshProjection()
    return {"success": True, "message": f"Created {layer_type} layer '{name}'", "data": {"layer_name": name}}

@register_handler("layer_delete")
def handle_layer_delete(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    layer = _find_layer(doc, layer_name)
    name = layer.name()
    layer.parentNode().removeChildNode(layer)
    doc.refreshProjection()
    return {"success": True, "message": f"Deleted layer '{name}'"}

@register_handler("layer_duplicate")
def handle_layer_duplicate(args):
    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        return {"success": False, "error": "No active layer"}
    new_name = args.get("new_name", f"{layer.name()} copy")
    duplicated = layer.duplicate()
    duplicated.setName(new_name)
    layer.parentNode().addChildNode(duplicated, layer)
    doc.refreshProjection()
    return {"success": True, "message": f"Duplicated layer as '{new_name}'", "data": {"layer_name": new_name}}

@register_handler("layer_set_opacity")
def handle_layer_set_opacity(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    opacity = args.get("opacity", 100)
    layer = _find_layer(doc, layer_name)
    layer.setOpacity(_opacity_to_krita(opacity))
    doc.refreshProjection()
    return {"success": True, "message": f"Set opacity of '{layer.name()}' to {opacity}%"}

@register_handler("layer_set_blend")
def handle_layer_set_blend(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    mode = args.get("mode", "normal")
    layer = _find_layer(doc, layer_name)
    krita_mode = BLEND_MODE_MAP.get(mode, mode)
    layer.setBlendingMode(krita_mode)
    doc.refreshProjection()
    return {"success": True, "message": f"Set blend mode of '{layer.name()}' to {mode}"}

@register_handler("layer_set_visible")
def handle_layer_set_visible(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    visible = args.get("visible", True)
    layer = _find_layer(doc, layer_name)
    layer.setVisible(visible)
    doc.refreshProjection()
    return {"success": True, "message": f"Set '{layer.name()}' visibility to {visible}"}

@register_handler("layer_move")
def handle_layer_move(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    direction = args.get("direction", "up")
    layer = _find_layer(doc, layer_name)
    parent = layer.parentNode()
    siblings = list(parent.childNodes())
    current_index = siblings.index(layer)
    new_index = current_index

    if direction == "up":
        if current_index < len(siblings) - 1:
            new_index = current_index + 1
        else:
            return {"success": True, "message": f"Layer '{layer.name()}' is already at top"}
    elif direction == "down":
        if current_index > 0:
            new_index = current_index - 1
        else:
            return {"success": True, "message": f"Layer '{layer.name()}' is already at bottom"}
    elif direction == "top":
        new_index = len(siblings) - 1
    elif direction == "bottom":
        new_index = 0

    if new_index == current_index:
        doc.refreshProjection()
        return {"success": True, "message": f"Layer '{layer.name()}' already at requested position"}

    siblings.pop(current_index)
    siblings.insert(new_index, layer)
    parent.setChildNodes(siblings)
    doc.refreshProjection()
    logger.info(f"Moved layer '{layer.name()}' {direction} from index {current_index} to {new_index}")
    return {"success": True, "message": f"Moved layer '{layer.name()}' {direction}"}

@register_handler("selection_create")
def handle_selection_create(args):
    doc = _get_document()
    sel_type = args.get("type", "rect")
    x = args.get("x", 0)
    y = args.get("y", 0)
    w = args.get("w", doc.width())
    h = args.get("h", doc.height())
    selection = Selection()
    if sel_type == "all":
        selection.select(0, 0, doc.width(), doc.height(), 255)
    elif sel_type == "none":
        doc.setSelection(None)
        return {"success": True, "message": "Cleared selection"}
    elif sel_type == "rect":
        selection.select(x, y, w, h, 255)
    elif sel_type == "ellipse":
        selection.select(x, y, w, h, 255)
        selection.shape = "ellipse"
    doc.setSelection(selection)
    return {"success": True, "message": f"Created {sel_type} selection"}

@register_handler("selection_modify")
def handle_selection_modify(args):
    doc = _get_document()
    action = args.get("action", "invert")
    value = args.get("value", 10)
    selection = doc.selection()
    if not selection:
        return {"success": False, "error": "No selection to modify"}
    if action == "invert":
        selection.invert()
    elif action == "feather":
        selection.feather(value)
    elif action == "grow":
        selection.grow(value, value)
    elif action == "shrink":
        selection.shrink(value, value)
    elif action == "smooth":
        selection.smooth()
    doc.setSelection(selection)
    return {"success": True, "message": f"Applied {action} to selection"}

@register_handler("selection_clear")
def handle_selection_clear(args):
    doc = _get_document()
    doc.setSelection(None)
    return {"success": True, "message": "Selection cleared"}

@register_handler("document_resize")
def handle_document_resize(args):
    doc = _get_document()
    width = args.get("width", doc.width())
    height = args.get("height", doc.height())
    anchor = args.get("anchor", "center")
    x_offset, y_offset = 0, 0
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
        "bottom-right": (width - old_w, height - old_h)
    }
    x_offset, y_offset = anchor_map.get(anchor, ((width - old_w) // 2, (height - old_h) // 2))
    doc.resizeImage(x_offset, y_offset, width, height, doc.resolution())
    doc.refreshProjection()
    return {"success": True, "message": f"Resized document to {width}x{height}"}

@register_handler("document_rotate")
def handle_document_rotate(args):
    doc = _get_document()
    degrees = args.get("degrees", 0)
    if degrees < -180 or degrees > 180:
        return {"success": False, "error": "Degrees must be between -180 and 180"}
    doc.rotateImage(degrees)
    doc.refreshProjection()
    return {"success": True, "message": f"Rotated document by {degrees} degrees"}

@register_handler("document_flip")
def handle_document_flip(args):
    doc = _get_document()
    direction = args.get("direction", "horizontal")
    if direction == "horizontal":
        doc.mirrorImage()
    elif direction == "vertical":
        doc.mirrorImageVertical()
    doc.refreshProjection()
    return {"success": True, "message": f"Flipped document {direction}"}

@register_handler("document_crop")
def handle_document_crop(args):
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
    action = Krita.instance().action("crop_to_selection")
    if action:
        action.trigger()
        doc.refreshProjection()
        return {"success": True, "message": "Cropped document to selection"}
    return {"success": False, "error": "Crop action not available"}

@register_handler("fill")
def handle_fill(args):
    doc = _get_document()
    fill_type = args.get("type", "foreground")
    color_hex = args.get("color")
    layer = doc.activeNode()
    if not layer:
        return {"success": False, "error": "No active layer"}
    krita = Krita.instance()
    view = krita.activeWindow().activeView()
    if color_hex:
        color = _hex_to_managed_color(color_hex, doc)
        if fill_type == "foreground":
            view.setForeGroundColor(color)
        elif fill_type == "background":
            view.setBackGroundColor(color)
    if fill_type == "foreground":
        action = Krita.instance().action("fill_foreground")
    elif fill_type == "background":
        action = Krita.instance().action("fill_background")
    elif fill_type == "pattern" and args.get("pattern_name"):
        return {"success": False, "error": "Pattern fill not yet implemented"}
    else:
        action = Krita.instance().action("fill_foreground")
    if action:
        action.trigger()
        doc.refreshProjection()
        return {"success": True, "message": f"Filled selection with {fill_type}"}
    return {"success": False, "error": "Fill action not available"}

def _hex_to_managed_color(hex_color, doc):
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    a = int(hex_color[6:8], 16) / 255.0 if len(hex_color) > 6 else 1.0
    color = ManagedColor(doc.colorModel(), doc.colorDepth(), doc.colorProfile())
    color.setComponents([r, g, b, a])
    return color

@register_handler("set_color")
def handle_set_color(args):
    doc = _get_document()
    target = args.get("target", "foreground")
    hex_color = args.get("hex", "#000000")
    krita = Krita.instance()
    view = krita.activeWindow().activeView()
    color = _hex_to_managed_color(hex_color, doc)
    if target == "foreground":
        view.setForeGroundColor(color)
    elif target == "background":
        view.setBackGroundColor(color)
    return {"success": True, "message": f"Set {target} color to {hex_color}"}

# ─── NEW TOOL HANDLERS ────────────────────────────────────────────────────────

@register_handler("selection_get_info")
def handle_selection_get_info(args):
    doc = _get_document()
    selection = doc.selection()
    if not selection:
        return {"success": False, "error": "No selection exists"}
    return {
        "success": True,
        "data": {
            "x": selection.x(),
            "y": selection.y(),
            "width": selection.width(),
            "height": selection.height()
        }
    }


@register_handler("layer_copy_selection")
def handle_layer_copy_selection(args):
    doc = _get_document()
    source_name = args.get("source_layer_name")
    new_name = args.get("new_layer_name", "Copied Selection")
    source = _find_layer(doc, source_name)
    selection = doc.selection()
    if not selection:
        return {"success": False, "error": "No selection exists. Create a selection first using selection_create."}
    x, y = selection.x(), selection.y()
    w, h = selection.width(), selection.height()
    pixel_data = source.pixelData(x, y, w, h)
    new_layer = doc.createNode(new_name, "paintlayer")
    new_layer.setPixelData(pixel_data, x, y, w, h)
    root = doc.rootNode()
    root.addChildNode(new_layer, source)
    doc.setActiveNode(new_layer)
    doc.refreshProjection()
    return {"success": True, "message": f"Copied selection region to new layer '{new_name}'", "data": {"layer_name": new_name, "x": x, "y": y, "width": w, "height": h}}


@register_handler("layer_set_active")
def handle_layer_set_active(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    if not layer_name:
        return {"success": False, "error": "layer_name is required"}
    layer = _find_layer(doc, layer_name)
    doc.setActiveNode(layer)
    return {"success": True, "message": f"Active layer set to '{layer_name}'"}


@register_handler("layer_merge_down")
def handle_layer_merge_down(args):
    doc = _get_document()
    layer = doc.activeNode()
    if not layer:
        return {"success": False, "error": "No active layer"}
    parent = layer.parentNode()
    siblings = list(parent.childNodes())
    idx = siblings.index(layer)
    if idx == 0:
        return {"success": False, "error": "No layer below to merge into"}
    below = siblings[idx - 1]
    below_name = below.name()
    layer_name = layer.name()
    action = Krita.instance().action("merge_down")
    if action:
        doc.setActiveNode(layer)
        action.trigger()
        doc.refreshProjection()
        return {"success": True, "message": f"Merged '{layer_name}' down into '{below_name}'"}
    return {"success": False, "error": "Merge down action not available"}


@register_handler("layer_flatten")
def handle_layer_flatten(args):
    doc = _get_document()
    action = Krita.instance().action("flatten_image")
    if action:
        action.trigger()
        doc.refreshProjection()
        return {"success": True, "message": "Flattened all visible layers"}
    return {"success": False, "error": "Flatten image action not available"}


@register_handler("layer_rename")
def handle_layer_rename(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    new_name = args.get("new_name")
    if not layer_name or not new_name:
        return {"success": False, "error": "Both layer_name and new_name are required"}
    layer = _find_layer(doc, layer_name)
    old_name = layer.name()
    layer.setName(new_name)
    doc.refreshProjection()
    return {"success": True, "message": f"Renamed layer '{old_name}' to '{new_name}'"}


@register_handler("layer_clear")
def handle_layer_clear(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    layer = _find_layer(doc, layer_name)
    old_active = doc.activeNode()
    doc.setActiveNode(layer)
    action = Krita.instance().action("edit_clear")
    if action:
        action.trigger()
        if old_active:
            doc.setActiveNode(old_active)
        doc.refreshProjection()
        return {"success": True, "message": f"Cleared content from '{layer.name()}'"}
    return {"success": False, "error": "Clear action not available"}


@register_handler("layer_transform")
def handle_layer_transform(args):
    doc = _get_document()
    layer_name = args.get("layer_name")
    action_type = args.get("action")
    layer = _find_layer(doc, layer_name)
    if not action_type:
        return {"success": False, "error": "action is required (flip_horizontal or flip_vertical)"}

    w, h = doc.width(), doc.height()
    pixel_data = layer.pixelData(0, 0, w, h)

    depth_bytes = {"U8": 1, "U16": 2, "F16": 2, "F32": 4}
    channel_map = {"GRAY": 1, "GRAYA": 2, "RGB": 3, "RGBA": 4, "CMYK": 4, "CMYKA": 5, "LAB": 3, "LABA": 4, "XYZ": 3, "XYZA": 4}
    channels = channel_map.get(doc.colorModel().upper(), 4)
    bpc = depth_bytes.get(doc.colorDepth(), 1)
    bpp = channels * bpc
    row_size = w * bpp

    data = bytearray(pixel_data)

    if action_type == "flip_horizontal":
        for y in range(h):
            row_start = y * row_size
            row = data[row_start:row_start + row_size]
            reversed_row = bytearray()
            for x in range(w - 1, -1, -1):
                px_start = x * bpp
                reversed_row.extend(row[px_start:px_start + bpp])
            data[row_start:row_start + row_size] = reversed_row
    elif action_type == "flip_vertical":
        for y in range(h // 2):
            top_start = y * row_size
            bot_start = (h - 1 - y) * row_size
            top_row = bytearray(data[top_start:top_start + row_size])
            bot_row = bytearray(data[bot_start:bot_start + row_size])
            data[top_start:top_start + row_size] = bot_row
            data[bot_start:bot_start + row_size] = top_row
    else:
        return {"success": False, "error": f"Unknown action: {action_type}. Supported: flip_horizontal, flip_vertical"}

    layer.setPixelData(bytes(data), 0, 0, w, h)
    doc.refreshProjection()
    return {"success": True, "message": f"Applied {action_type} to '{layer.name()}'"}


@register_handler("document_scale")
def handle_document_scale(args):
    doc = _get_document()
    width = args.get("width", doc.width())
    height = args.get("height", doc.height())
    if width < 1 or height < 1:
        return {"success": False, "error": "Width and height must be at least 1"}
    try:
        doc.scaleImage(width, height, doc.resolution(), doc.resolution(), "Bicubic")
    except Exception as e:
        return {"success": False, "error": f"Failed to scale image: {str(e)}. The Krita API may not support scaling for this document type."}
    doc.refreshProjection()
    return {"success": True, "message": f"Scaled document to {width}x{height}"}


@register_handler("document_new")
def handle_document_new(args):
    krita = Krita.instance()
    width = args.get("width", 1920)
    height = args.get("height", 1080)
    name = args.get("name", "Untitled")
    resolution = args.get("resolution", 72.0)
    if width < 1 or height < 1:
        return {"success": False, "error": "Width and height must be at least 1"}
    doc = krita.createDocument(width, height, name, "RGBA", "U8", resolution)
    if not doc:
        return {"success": False, "error": "Failed to create new document"}
    window = krita.activeWindow()
    if window:
        window.addView(doc)
    return {"success": True, "message": f"Created new document '{name}' ({width}x{height}, {resolution} PPI)", "data": {"width": width, "height": height, "name": name}}


@register_handler("export_image")
def handle_export_image(args):
    doc = _get_document()
    path = args.get("path")
    file_format = args.get("format", "png")
    if not path:
        return {"success": False, "error": "path is required"}
    current_path = doc.fileName()
    if current_path and os.path.normpath(path) == os.path.normpath(current_path):
        return {"success": False, "error": "Cannot overwrite the currently open document. Export to a different file path."}
    if file_format == "jpg":
        file_format = "jpeg"
    base, ext = os.path.splitext(path)
    if not ext:
        path = f"{path}.{file_format}"
    info = InfoObject()
    if file_format == "jpeg":
        info.setProperty("quality", 90)
    success = doc.exportImage(path, info)
    if success:
        return {"success": True, "message": f"Exported document to '{path}'"}
    return {"success": False, "error": f"Failed to export to '{path}'. Check that the file format is supported and the path is writable."}


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
        return result if result else {"success": True}
    except Exception as e:
        log_exception(e, f"execute_tool({tool_name})")
        return {"success": False, "error": str(e)}

_cached_tools = None


def generate_tools():
    """Generate tool schemas for the API. Results are cached for the session."""
    global _cached_tools
    if _cached_tools is not None:
        logger.debug(f"Returning {len(_cached_tools)} cached tool schemas")
        return _cached_tools
    
    logger.debug("generate_tools() called (first invocation, building cache)")
    krita = Krita.instance()
    filter_names = list(krita.filters())
    logger.debug(f"Discovered {len(filter_names)} filters: {filter_names[:10]}...")
    
    anchor_options = ["center", "top-left", "top", "top-right", "left", 
                      "right", "bottom-left", "bottom", "bottom-right"]
    selection_types = ["all", "rect", "ellipse", "none"]
    modify_actions = ["invert", "feather", "grow", "shrink", "smooth"]
    layer_types = ["paint", "group", "vector"]
    move_directions = ["up", "down", "top", "bottom"]
    fill_types = ["foreground", "background", "pattern"]
    color_targets = ["foreground", "background"]
    flip_directions = ["horizontal", "vertical"]
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "image_info",
                "description": "Get document info: dimensions, layers, colors",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "apply_filter",
                "description": "Apply filter to active layer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": filter_names},
                        "intensity": {"type": "number", "minimum": 0, "maximum": 100}
                    },
                    "required": ["name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_create",
                "description": "Create new layer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": layer_types},
                        "opacity": {"type": "number", "minimum": 0, "maximum": 100},
                        "blend_mode": {"type": "string", "enum": BLEND_MODES}
                    },
                    "required": ["name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_delete",
                "description": "Delete layer (default: active)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "layer_name": {"type": "string"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_duplicate",
                "description": "Duplicate active layer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "new_name": {"type": "string"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_set_opacity",
                "description": "Set layer opacity",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "opacity": {"type": "number", "minimum": 0, "maximum": 100},
                        "layer_name": {"type": "string"}
                    },
                    "required": ["opacity"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_set_blend",
                "description": "Set layer blend mode",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": BLEND_MODES},
                        "layer_name": {"type": "string"}
                    },
                    "required": ["mode"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_set_visible",
                "description": "Set layer visibility",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "visible": {"type": "boolean"},
                        "layer_name": {"type": "string"}
                    },
                    "required": ["visible"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_move",
                "description": "Move layer in stack",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "enum": move_directions},
                        "layer_name": {"type": "string"}
                    },
                    "required": ["direction"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "selection_create",
                "description": "Create selection",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": selection_types},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "w": {"type": "number"},
                        "h": {"type": "number"}
                    },
                    "required": ["type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "selection_modify",
                "description": "Modify current selection",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": modify_actions},
                        "value": {"type": "number"}
                    },
                    "required": ["action"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "selection_clear",
                "description": "Deselect all",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "document_resize",
                "description": "Resize canvas",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                        "anchor": {"type": "string", "enum": anchor_options}
                    },
                    "required": ["width", "height"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "document_rotate",
                "description": "Rotate document",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "degrees": {"type": "number", "minimum": -180, "maximum": 180}
                    },
                    "required": ["degrees"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "document_flip",
                "description": "Flip document",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "enum": flip_directions}
                    },
                    "required": ["direction"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "document_crop",
                "description": "Crop to bounds or selection",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "w": {"type": "number"},
                        "h": {"type": "number"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fill",
                "description": "Fill selection or layer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": fill_types},
                        "color": {"type": "string"},
                        "pattern_name": {"type": "string"}
                    },
                    "required": ["type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "set_color",
                "description": "Set foreground/background color",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "enum": color_targets},
                        "hex": {"type": "string"}
                    },
                    "required": ["target", "hex"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "selection_get_info",
                "description": "Get current selection bounds (x, y, width, height). Returns error if no selection exists. Use this to check what area is selected before operating on it.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_copy_selection",
                "description": "Copy the current selection region from a source layer into a new layer. The new layer contains only the pixels within the selection, placed at the same position. Requires an existing selection. Use this to extract parts of an image onto separate layers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_layer_name": {"type": "string", "description": "Layer to copy from (default: active layer)"},
                        "new_layer_name": {"type": "string", "description": "Name for the new layer (default: 'Copied Selection')"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_set_active",
                "description": "Set the active layer by name. The active layer is the target for most operations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "layer_name": {"type": "string", "description": "Name of the layer to make active"}
                    },
                    "required": ["layer_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_merge_down",
                "description": "Merge the active layer with the layer directly below it. The result replaces both layers. Cannot merge the bottommost layer.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_flatten",
                "description": "Flatten all visible layers into a single layer. Hidden layers are discarded.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_rename",
                "description": "Rename a layer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "layer_name": {"type": "string", "description": "Current name of the layer"},
                        "new_name": {"type": "string", "description": "New name for the layer"}
                    },
                    "required": ["layer_name", "new_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_clear",
                "description": "Clear all pixel content from a layer (make it fully transparent). If a selection exists, only clears within the selection. Otherwise clears the entire layer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "layer_name": {"type": "string", "description": "Layer to clear (default: active layer)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "layer_transform",
                "description": "Flip a layer horizontally or vertically. Works by manipulating pixel data directly, supporting any color model and depth.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "layer_name": {"type": "string", "description": "Layer to transform (default: active layer)"},
                        "action": {"type": "string", "enum": ["flip_horizontal", "flip_vertical"]}
                    },
                    "required": ["action"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "document_scale",
                "description": "Scale the entire document to new dimensions. This resizes both the canvas and all layer content. Different from document_resize which only changes canvas size.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "number", "minimum": 1, "description": "New width in pixels"},
                        "height": {"type": "number", "minimum": 1, "description": "New height in pixels"}
                    },
                    "required": ["width", "height"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "document_new",
                "description": "Create a new blank document and open it in the active window. The new document uses RGBA 8-bit color mode.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "number", "minimum": 1, "description": "Width in pixels (default: 1920)"},
                        "height": {"type": "number", "minimum": 1, "description": "Height in pixels (default: 1080)"},
                        "name": {"type": "string", "description": "Document name (default: 'Untitled')"},
                        "resolution": {"type": "number", "description": "Resolution in PPI (default: 72)"}
                    },
                    "required": ["width", "height"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "export_image",
                "description": "Export the current document to a file. IMPORTANT: Cannot overwrite the currently open document — must export to a new file path. Supports PNG and JPEG formats.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to save to (must not be the currently open file)"},
                        "format": {"type": "string", "enum": ["png", "jpg"]}
                    },
                    "required": ["path"]
                }
            }
        }
    ]
    _cached_tools = tools
    logger.debug(f"Cached {len(tools)} tool schemas")
    return tools
