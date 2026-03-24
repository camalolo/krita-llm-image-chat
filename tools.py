from krita import Krita, Selection, InfoObject, ManagedColor
import json
import logging
import traceback

LOG_PATH = "C:/Users/camal/AppData/Roaming/krita/pykrita/llm_image_chat/llm_image_chat.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def log_exception(e, context=""):
    logger.error(f"EXCEPTION in {context}: {type(e).__name__}: {str(e)}")
    logger.debug(traceback.format_exc())

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
    if layer_name:
        logger.debug(f"Finding layer by name: {layer_name}")
        root = doc.rootNode()
        for node in root.childNodes():
            if node.name() == layer_name:
                logger.debug(f"Found layer: {layer_name}")
                return node
        logger.error(f"Layer not found: {layer_name}")
        raise Exception(f"Layer not found: {layer_name}")
    layer = doc.activeNode()
    if not layer:
        logger.error("No active layer found")
        raise Exception("No active layer")
    logger.debug(f"Using active layer: {layer.name()}")
    return layer

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
            for prop in config.properties():
                prop_name = prop.name.lower()
                if any(x in prop_name for x in ["radius", "strength", "intensity", "amount", "level"]):
                    logger.debug(f"Setting property {prop.name} to {intensity}")
                    try:
                        config.setProperty(prop.name, intensity)
                    except Exception as e:
                        logger.warning(f"Failed to set property {prop.name}: {e}")
                    break
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
    siblings = parent.childNodes()
    current_index = siblings.index(layer)
    if direction == "up" and current_index < len(siblings) - 1:
        parent.removeChildNode(layer)
        parent.addChildNode(layer, siblings[current_index + 1])
    elif direction == "down" and current_index > 0:
        parent.removeChildNode(layer)
        parent.addChildNode(layer, siblings[current_index - 2] if current_index > 1 else None)
    elif direction == "top":
        parent.removeChildNode(layer)
        parent.addChildNode(layer, None)
    elif direction == "bottom":
        parent.removeChildNode(layer)
        parent.addChildNode(layer, siblings[0] if siblings else None)
    doc.refreshProjection()
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
    if x is None or y is None or w is None or h is None:
        selection = doc.selection()
        if selection:
            x = selection.x()
            y = selection.y()
            w = selection.width()
            h = selection.height()
        else:
            return {"success": False, "error": "No bounds specified and no selection exists"}
    doc.cropImage(x, y, w, h)
    doc.refreshProjection()
    return {"success": True, "message": f"Cropped document to {w}x{h}"}

@register_handler("fill")
def handle_fill(args):
    doc = _get_document()
    fill_type = args.get("type", "foreground")
    color_hex = args.get("color")
    pattern_name = args.get("pattern_name")
    layer = doc.activeNode()
    if not layer:
        return {"success": False, "error": "No active layer"}
    selection = doc.selection()
    if not selection:
        selection = Selection()
        selection.select(0, 0, doc.width(), doc.height(), 255)
    krita = Krita.instance()
    view = krita.activeWindow().activeView()
    if color_hex:
        color = _hex_to_managed_color(color_hex, doc)
        if fill_type == "foreground":
            view.setForeGroundColor(color)
        elif fill_type == "background":
            view.setBackGroundColor(color)
    if fill_type == "foreground":
        fg_color = view.foregroundColor()
        layer.setPixelData(fg_color.data(), selection.x(), selection.y(), selection.width(), selection.height())
    elif fill_type == "background":
        bg_color = view.backgroundColor()
        layer.setPixelData(bg_color.data(), selection.x(), selection.y(), selection.width(), selection.height())
    elif fill_type == "pattern" and pattern_name:
        return {"success": False, "error": "Pattern fill not yet implemented"}
    doc.refreshProjection()
    return {"success": True, "message": f"Filled selection with {fill_type}"}

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

def generate_tools():
    logger.debug("generate_tools() called")
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
        }
    ]
    logger.debug(f"Generated {len(tools)} tool schemas")
    return tools
