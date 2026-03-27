"""layer and layer_stack tools – create, delete, duplicate, rename, reorder, merge layers."""

from krita import Krita

from . import _registry
from ._registry import (
    register_handler, TOOL_SCHEMAS, SCHEMA_BLEND_MODES, MOVE_DIRECTIONS,
    _get_document, _find_layer,
)
from ..pixel_ops import _BLEND_MODE_MAP
from ..config import logger

TOOL_SCHEMAS["layer"] = {
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
}


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

        _registry._last_property_backup = {
            "layer_name": layer.name(),
            "prev_opacity": prev_opacity,
            "prev_blend_mode": prev_blend_mode,
            "prev_visible": prev_visible,
        }

        doc.refreshProjection()
        return {"success": True, "message": f"Updated '{layer.name()}': {', '.join(changed)}"}

    return {"success": False, "error": f"Unknown layer action: {action}"}


TOOL_SCHEMAS["layer_stack"] = {
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
                    "enum": MOVE_DIRECTIONS,
                    "description": "Move direction for move action",
                },
                "position": {"type": "integer", "description": "Absolute index for move action"},
                "source_layer_name": {"type": "string", "description": "Source layer for extract_selection"},
                "new_layer_name": {"type": "string", "description": "New layer name for extract_selection"},
            },
            "required": ["action"],
        },
    },
}


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
