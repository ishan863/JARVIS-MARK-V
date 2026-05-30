"""
remote_server.py — FastAPI + WebSocket server for iOS remote control.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if TYPE_CHECKING:
    from core.remote_manager import RemoteManager

STATIC_DIR = Path(__file__).parent / "static"

# Disable pyautogui failsafe globally so edge-of-screen clicks don't crash
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.0
except Exception:
    pass


# ── Request models ─────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    text: str
    pin: str = ""

class ToolRequest(BaseModel):
    tool: str
    params: dict = {}
    pin: str = ""

class VoiceRequest(BaseModel):
    audio: str
    format: str = "wav"
    pin: str = ""

class ClickRequest(BaseModel):
    x_pct: float
    y_pct: float
    button: str = "left"   # left | right | double
    pin: str = ""

class TypeRequest(BaseModel):
    text: str
    pin: str = ""

class KeyRequest(BaseModel):
    key: str
    pin: str = ""

class ScrollRequest(BaseModel):
    direction: str = "down"
    amount: int = 3
    pin: str = ""

class DragRequest(BaseModel):
    x1_pct: float
    y1_pct: float
    x2_pct: float
    y2_pct: float
    pin: str = ""


# ── App factory ────────────────────────────────────────────────────────────

def build_app(manager: "RemoteManager") -> FastAPI:
    app = FastAPI(title="JARVIS Remote", docs_url=None, redoc_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup():
        manager._uvicorn_loop = asyncio.get_event_loop()
        print(f"[Remote] FastAPI ready — http://{manager.ip}:{manager.port}  PIN={manager.pin}")

    # ── Static files ───────────────────────────────────────────────────
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return FileResponse(str(html_path))
        return HTMLResponse("<h1>JARVIS Remote — static files missing</h1>")

    @app.get("/manifest.json")
    async def manifest():
        p = STATIC_DIR / "manifest.json"
        if p.exists():
            return FileResponse(str(p), media_type="application/json")
        return JSONResponse({})

    # ── REST endpoints ─────────────────────────────────────────────────

    @app.get("/api/health")
    async def health():
        return {"ok": True, "pin": manager.pin, "ip": manager.ip, "port": manager.port}

    @app.get("/api/pair")
    async def pair_info():
        return {
            "pin": manager.pin,
            "ip": manager.ip,
            "port": manager.port,
            "url": f"http://{manager.ip}:{manager.port}",
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        manager.route_text_to_jarvis(req.text)
        return {"status": "sent"}

    @app.post("/api/screenshot")
    async def screenshot():
        loop = asyncio.get_event_loop()
        img = await loop.run_in_executor(None, manager.take_screenshot)
        if img:
            return {"image": img}
        return JSONResponse({"error": "Screenshot failed"}, status_code=500)

    @app.post("/api/tool")
    async def run_tool(req: ToolRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: manager.execute_tool(req.tool, req.params)
        )
        return {"result": result}

    @app.post("/api/voice")
    async def voice(req: VoiceRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        try:
            raw = base64.b64decode(req.audio)
            pcm = _convert_to_pcm16(raw, req.format)
            manager.route_audio_to_jarvis(pcm)
            return {"status": "sent", "bytes": len(pcm)}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/click")
    async def click(req: ClickRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _do_click(req.x_pct, req.y_pct, req.button)
        )
        return {"result": result}

    @app.post("/api/type")
    async def type_text(req: TypeRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: _do_type(req.text))
        return {"result": result}

    @app.post("/api/key")
    async def press_key(req: KeyRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: _do_key(req.key))
        return {"result": result}

    @app.post("/api/scroll")
    async def scroll(req: ScrollRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _do_scroll(req.direction, req.amount)
        )
        return {"result": result}

    @app.post("/api/drag")
    async def drag(req: DragRequest):
        if req.pin != manager.pin:
            return JSONResponse({"error": "Invalid PIN"}, status_code=401)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _do_drag(req.x1_pct, req.y1_pct, req.x2_pct, req.y2_pct)
        )
        return {"result": result}

    # ── WebSocket ──────────────────────────────────────────────────────

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        with manager._clients_lock:
            manager._clients[ws] = {"name": "Unknown", "paired": False}
        print(f"[Remote] WS connected — {ws.client}")
        try:
            await ws.send_json({"type": "hello", "data": "JARVIS Remote"})
            async for raw in ws.iter_text():
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                await _handle_ws_message(ws, msg, manager)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[Remote] WS error: {e}")
        finally:
            with manager._clients_lock:
                manager._clients.pop(ws, None)
            print(f"[Remote] WS disconnected")

    return app


# ── WebSocket message handler ──────────────────────────────────────────────

async def _handle_ws_message(ws: WebSocket, msg: dict, manager: "RemoteManager"):
    mtype = msg.get("type", "")

    # ── Pairing ────────────────────────────────────────────────────────
    if mtype == "pair":
        pin = str(msg.get("pin", ""))
        if pin == manager.pin:
            device_name = msg.get("device_name", "iPhone")
            device_info = msg.get("device_info", {})
            
            with manager._clients_lock:
                manager._clients[ws]["paired"] = True
                manager._clients[ws]["name"] = device_name
                manager._clients[ws]["info"] = device_info
            
            await ws.send_json({"type": "paired", "data": "Connected to JARVIS"})
            
            # Log device info
            print(f"[Remote] Paired: {device_name}")
            if device_info:
                screen = device_info.get("screen", {})
                print(f"[Remote]   Screen: {screen.get('width')}x{screen.get('height')} @ {screen.get('pixelRatio')}x")
                print(f"[Remote]   Orientation: {screen.get('orientation', 'unknown')}")
                if device_info.get("battery"):
                    bat = device_info["battery"]
                    print(f"[Remote]   Battery: {bat.get('level')}% {'(charging)' if bat.get('charging') else ''}")
        else:
            await ws.send_json({"type": "error", "data": "Wrong PIN"})
        return

    # All other messages require pairing
    with manager._clients_lock:
        paired = manager._clients.get(ws, {}).get("paired", False)
    if not paired:
        await ws.send_json({"type": "error", "data": "Not paired"})
        return

    loop = asyncio.get_event_loop()

    if mtype == "text":
        text = msg.get("data", "")
        if text:
            # Log on server/PC
            with manager._clients_lock:
                device_name = manager._clients.get(ws, {}).get("name", "Mobile")
            print(f"[Remote] {device_name}: {text}")
            
            # Route to JARVIS
            manager.route_text_to_jarvis(text)
            await ws.send_json({"type": "ack", "data": "sent"})

    elif mtype == "audio":
        try:
            raw = base64.b64decode(msg.get("data", ""))
            fmt = msg.get("format", "wav")
            pcm = _convert_to_pcm16(raw, fmt)
            manager.route_audio_to_jarvis(pcm)
            await ws.send_json({"type": "ack", "data": "audio_sent"})
        except Exception as e:
            await ws.send_json({"type": "error", "data": str(e)})

    elif mtype == "screenshot":
        img = await loop.run_in_executor(None, manager.take_screenshot)
        if img:
            await ws.send_json({"type": "screenshot", "data": img})
        else:
            await ws.send_json({"type": "error", "data": "Screenshot failed"})

    elif mtype == "click":
        x_pct = float(msg.get("x_pct", 0.5))
        y_pct = float(msg.get("y_pct", 0.5))
        button = msg.get("button", "left")
        result = await loop.run_in_executor(None, lambda: _do_click(x_pct, y_pct, button))
        await ws.send_json({"type": "click_result", "data": result})

    elif mtype == "type":
        text = msg.get("data", "")
        result = await loop.run_in_executor(None, lambda: _do_type(text))
        await ws.send_json({"type": "type_result", "data": result})

    elif mtype == "key":
        key = msg.get("data", "")
        result = await loop.run_in_executor(None, lambda: _do_key(key))
        await ws.send_json({"type": "key_result", "data": result})

    elif mtype == "scroll":
        direction = msg.get("direction", "down")
        amount = int(msg.get("amount", 3))
        result = await loop.run_in_executor(None, lambda: _do_scroll(direction, amount))
        await ws.send_json({"type": "scroll_result", "data": result})

    elif mtype == "drag":
        x1 = float(msg.get("x1_pct", 0))
        y1 = float(msg.get("y1_pct", 0))
        x2 = float(msg.get("x2_pct", 0))
        y2 = float(msg.get("y2_pct", 0))
        result = await loop.run_in_executor(None, lambda: _do_drag(x1, y1, x2, y2))
        await ws.send_json({"type": "drag_result", "data": result})

    elif mtype == "tool":
        tool = msg.get("tool", "")
        params = msg.get("params", {})
        result = await loop.run_in_executor(
            None, lambda: manager.execute_tool(tool, params)
        )
        await ws.send_json({"type": "tool_result", "data": result})

    elif mtype == "ping":
        await ws.send_json({"type": "pong"})


# ── Desktop control helpers ────────────────────────────────────────────────

def _do_click(x_pct: float, y_pct: float, button: str = "left") -> str:
    try:
        import pyautogui
        w, h = pyautogui.size()
        x = int(x_pct * w)
        y = int(y_pct * h)
        if button == "double":
            pyautogui.doubleClick(x, y)
        elif button == "right":
            pyautogui.rightClick(x, y)
        else:
            pyautogui.click(x, y)
        return f"Clicked ({x},{y}) [{button}]"
    except Exception as e:
        return f"Click failed: {e}"


def _do_type(text: str) -> str:
    try:
        import pyautogui
        # Use clipboard for non-ASCII / long text — faster and more reliable
        try:
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except ImportError:
            pyautogui.write(text, interval=0.02)
        return f"Typed: {text[:60]}"
    except Exception as e:
        return f"Type failed: {e}"


def _do_key(key: str) -> str:
    try:
        import pyautogui
        key = key.strip()
        if "+" in key:
            parts = [k.strip() for k in key.split("+")]
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(key)
        return f"Key: {key}"
    except Exception as e:
        return f"Key failed: {e}"


def _do_scroll(direction: str, amount: int) -> str:
    try:
        import pyautogui
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks)
        return f"Scrolled {direction} {amount}"
    except Exception as e:
        return f"Scroll failed: {e}"


def _do_drag(x1_pct: float, y1_pct: float, x2_pct: float, y2_pct: float) -> str:
    try:
        import pyautogui
        w, h = pyautogui.size()
        x1, y1 = int(x1_pct * w), int(y1_pct * h)
        x2, y2 = int(x2_pct * w), int(y2_pct * h)
        pyautogui.moveTo(x1, y1, duration=0.1)
        pyautogui.dragTo(x2, y2, duration=0.3, button="left")
        return f"Dragged ({x1},{y1})→({x2},{y2})"
    except Exception as e:
        return f"Drag failed: {e}"


# ── Audio conversion ───────────────────────────────────────────────────────

def _convert_to_pcm16(raw: bytes, fmt: str) -> bytes:
    """Convert audio bytes to PCM 16kHz 16-bit mono for Gemini Live API."""
    if fmt == "pcm16":
        return raw
    try:
        import wave
        import io as _io
        import numpy as np

        with wave.open(_io.BytesIO(raw)) as wf:
            channels = wf.getnchannels()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        samples = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
        if rate != 16000:
            ratio = 16000 / rate
            new_len = int(len(samples) * ratio)
            indices = np.linspace(0, len(samples) - 1, new_len)
            samples = np.interp(indices, np.arange(len(samples)), samples).astype(np.int16)
        return samples.tobytes()
    except Exception:
        return raw
