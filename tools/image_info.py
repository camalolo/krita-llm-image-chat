"""image_info tool – get document metadata (dimensions, resolution, color model, layers)."""

from ._registry import register_handler, TOOL_SCHEMAS, _get_document

TOOL_SCHEMAS["image_info"] = {
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
}


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
