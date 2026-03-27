"""Auto-loading tools package.

All .py files in this directory (except __init__.py and _-prefixed files)
are imported automatically. Each tool file registers its handler via
@register_handler("name") and its schema via TOOL_SCHEMAS["name"] = {...}.

Public API (re-exported for consumer imports):
- execute_tool, generate_tools, classify_tools, CORE_TOOLS
- TOOL_HANDLERS, TOOL_SCHEMAS
"""

import importlib
import os

# Import shared infrastructure first (populates TOOL_HANDLERS, TOOL_SCHEMAS dicts)
from . import _registry
from . import classify

# Re-export public API
from ._registry import TOOL_HANDLERS, TOOL_SCHEMAS, execute_tool
from .classify import generate_tools, classify_tools, CORE_TOOLS

# Auto-discover and import all tool modules (side-effect: registers handlers + schemas)
_tools_dir = os.path.dirname(__file__)
for _fname in sorted(os.listdir(_tools_dir)):
    if _fname.endswith(".py") and not _fname.startswith("_") and _fname != "__init__.py":
        _mod_name = f".{_fname[:-3]}"
        try:
            importlib.import_module(_mod_name, package=__name__)
        except Exception:
            import traceback
            traceback.print_exc()  # Visible in Krita's Python console during dev
