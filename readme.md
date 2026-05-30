# MARK XL

AI Operating Assistant upgraded from MARK XXXIX.

MARK XL keeps the existing real-time voice pipeline intact and upgrades the desktop experience around it with a modern command dashboard, agent surfaces, memory/workflow panels, file intelligence entry points, browser/vision controls, and a Figma-aligned futuristic UI.

## What Is Preserved

- Existing Gemini live voice pipeline
- Existing wake/listen/speak state bridge
- Existing assistant tool declarations and routing in `main.py`
- Existing desktop control, browser control, webcam/screen processing, reminders, file handling, and memory modules

## What Is Upgraded

- MARK XL dashboard shell in PyQt6
- Sidebar navigation for Home, Chats, Agents, Automation, Browser, Files, Memory, Vision, Workflows, Analytics, and Settings
- Floating AI orb with listening/thinking/speaking/muted states
- Live activity feed wired to assistant logs
- AI command palette on `Ctrl + Space` and `Ctrl + K`
- Multi-agent, memory, workflow, browser, vision, file, analytics, and settings surfaces
- Smart file intake panel with drag/drop support
- System monitor widgets for CPU, RAM, GPU, and disk

## Figma Reference

The MARK XL desktop dashboard has been recreated in Figma as the design reference:

https://www.figma.com/design/Z7gKinNCmmzhPuxAL3aeqR

## Quick Start

```bash
pip install -r requirements.txt
playwright install
python main.py
```

The app still starts through `main.py`. The compatibility module `ui.py` exports the upgraded `JarvisUI` from `mark_xl_ui.py`, so the voice system does not need to change.

## Shortcuts

- `Ctrl + Space` or `Ctrl + K`: AI command palette
- `F4`: Toggle microphone mute
- `F11`: Toggle fullscreen

## Notes

This upgrade focuses on a stable MARK XL desktop shell around the existing assistant. The larger React/Tauri/FastAPI architecture remains the target architecture for a future migration, but this repository now has a production-style UI foundation without breaking the current working voice assistant.
