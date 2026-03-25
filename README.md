# Krita LLM Image Chat

A Krita plugin that adds a chat dockable panel to your workspace, letting you control Krita with natural language through an LLM. Describe what you want — the AI does it.

**Beta** — actively developed, features may change.

## Features

- **Natural language image editing** — describe edits in plain English, the LLM translates them into actions
- **Vision support** — optionally send the current layer as an image so the LLM can see what it's working on
- **29 tools** covering layers, selections, filters, document operations, colors, and more
- **Multi-step tool loops** — the LLM chains tools automatically until the task is done
- **Abort support** — cancel long-running requests at any time
- **Multiple free models** — ships with a curated list of free OpenRouter models

## Available Tools

| Category | Tools |
|----------|-------|
| **Document** | `image_info`, `document_resize`, `document_rotate`, `document_flip`, `document_crop`, `document_scale`, `document_new`, `export_image` |
| **Layers** | `layer_create`, `layer_delete`, `layer_duplicate`, `layer_set_opacity`, `layer_set_blend`, `layer_set_visible`, `layer_move`, `layer_set_active`, `layer_rename`, `layer_merge_down`, `layer_flatten`, `layer_clear`, `layer_copy_selection`, `layer_transform` |
| **Selections** | `selection_create`, `selection_modify`, `selection_clear`, `selection_get_info` |
| **Filters** | `apply_filter` (all Krita filters dynamically available) |
| **Colors / Fill** | `set_color`, `fill` |

### Example prompts

- *"Split the image into four equal parts on separate layers"*
- *"Apply a Gaussian blur with 30% intensity"*
- *"Flip the active layer horizontally and set opacity to 50%"*
- *"Create a new 800x600 document and fill it with red"*
- *"Export this as a PNG to my desktop"*

## Installation

1. Clone or download this repository
2. Copy the `llm_image_chat` folder into your Krita plugins directory:

   - **Windows**: `%APPDATA%\krita\pykrita\`
   - **Linux**: `~/.local/share/krita/pykrita/`
   - **macOS**: `~/Library/Application Support/krita/pykrita/`

3. Restart Krita
4. Open **Settings > Configure Krita > Python Plugins** and enable `LLM Image Chat`
5. The panel appears as a dockable widget (usually on the right side)

## Setup

1. Click the **Settings** button in the plugin panel
2. Enter your [OpenRouter](https://openrouter.ai/) API key
3. Select a model (defaults to a free vision-capable model)
4. Adjust temperature if desired
5. Start chatting

## How It Works

```
You type a message
       │
       ▼
┌──────────────────┐     ┌─────────────────┐
│  Image captured   │────▶│  OpenRouter API │
│  (optional JPEG)  │     │  (LLM + tools)  │
└──────────────────┘     └────────┬────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │  LLM decides: text reply   │
                    │  or tool call(s)           │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │  Tool executed in Krita    │
                    │  Result fed back to LLM    │
                    │  (loops until done)        │
                    └─────────────┬─────────────┘
                                  │
                                  ▼
                         Response shown in chat
```

The plugin sends your message (and optionally the current layer as a JPEG) to an LLM via the OpenRouter API. The LLM can call Krita tools — the results are fed back so it can chain actions. This continues until the LLM produces a final text response.

## Architecture

```
llm_image_chat/
├── __init__.py          # Plugin entry point, registers dock widget
├── llm_chat.py          # Main UI (chat panel, message history, abort)
├── api_client.py        # HTTP layer, tool-call dispatch, conversation worker
├── tools.py             # 29 tool schemas + handler implementations
├── config.py            # Constants, system prompt, model list, logging
├── image_capture.py     # Captures active layer as JPEG base64
├── settings_dialog.py   # Qt settings dialog (API key, model, temperature)
├── models.json          # OpenRouter model catalog
└── settings.json        # User settings (gitignored)
```

## Requirements

- Krita 5.0+ with Python plugin support
- An [OpenRouter](https://openrouter.ai/) API key
- Internet connection

## License

MIT
