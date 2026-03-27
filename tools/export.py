"""Save, export, and split-export documents."""

import os
from krita import Krita, Selection, InfoObject
from ._registry import register_handler, TOOL_SCHEMAS, _get_document
from ..config import logger

TOOL_SCHEMAS["export"] = {
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
}

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
