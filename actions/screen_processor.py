from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False

import google.genai as genai
from google.genai import types as gtypes

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config_key(key: str, value) -> None:
    try:
        cfg = _load_config()
        cfg[key] = value
        _CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[Vision] ⚠️  Could not save config key '{key}': {e}")


def _get_api_key() -> str:
    key = _load_config().get("gemini_api_key", "")
    if not key:
        raise RuntimeError("gemini_api_key not found in config.")
    return key


def _get_os() -> str:
    return _load_config().get("os_system", "windows").lower()

_LIVE_MODEL         = "gemini-3.1-flash-live-preview"
_CHANNELS           = 1
_RECEIVE_SAMPLE_RATE = 24_000
_CHUNK_SIZE         = 1_024

_IMG_MAX_W = 1280
_IMG_MAX_H = 720
_JPEG_Q    = 85

_SYSTEM_PROMPT = (
    "You are JARVIS, an advanced AI assistant. "
    "Analyze the provided image with precision and intelligence. "
    "Be concise and direct — maximum two sentences unless the user's question "
    "requires more detail. "
    "Address the user respectfully. "
    "Always call the appropriate tool; never simulate results."
)


def _compress(img_bytes: bytes, source_format: str = "PNG") -> tuple[bytes, str]:
    if not _PIL:
        return img_bytes, f"image/{source_format.lower()}"

    try:
        img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[Vision] ⚠️  Image compress failed: {e}")
        return img_bytes, f"image/{source_format.lower()}"

def _capture_screen() -> tuple[bytes, str]:
    """Capture screen, compress to _IMG_MAX_W x _IMG_MAX_H. Returns (image_bytes, mime_type)."""
    if not _MSS:
        raise RuntimeError("mss is not installed. Run: pip install mss")

    with mss.mss() as sct:
        monitors = sct.monitors          # [0] = all combined, [1..n] = real screens
        target   = monitors[1] if len(monitors) > 1 else monitors[0]
        shot     = sct.grab(target)
        png      = mss.tools.to_png(shot.rgb, shot.size)

    return _compress(png, "PNG")


def _capture_screen_with_scale() -> tuple[bytes, str, float, float]:
    """Capture screen and return (image_bytes, mime_type, scale_x, scale_y).
    scale_x/y are factors to convert coordinates on the compressed image
    back to original screen coordinates."""
    if not _MSS:
        raise RuntimeError("mss is not installed. Run: pip install mss")

    with mss.mss() as sct:
        monitors = sct.monitors
        target   = monitors[1] if len(monitors) > 1 else monitors[0]
        shot     = sct.grab(target)
        png      = mss.tools.to_png(shot.rgb, shot.size)

    orig_w, orig_h = shot.size
    compressed, mime_type = _compress(png, "PNG")

    # Determine actual compressed dimensions
    if _PIL:
        img = PIL.Image.open(io.BytesIO(compressed))
        comp_w, comp_h = img.size
    else:
        comp_w, comp_h = _IMG_MAX_W, _IMG_MAX_H

    scale_x = orig_w / comp_w if comp_w > 0 else 1.0
    scale_y = orig_h / comp_h if comp_h > 0 else 1.0

    return compressed, mime_type, scale_x, scale_y


def _cv2_backend() -> int:
    """Return the best OpenCV camera backend for the current OS."""
    if not _CV2:
        return 0
    os_name = _get_os()
    if os_name == "windows":
        return cv2.CAP_DSHOW    
    if os_name == "mac":
        return cv2.CAP_AVFOUNDATION  
    return cv2.CAP_ANY


def _probe_camera(index: int, backend: int, warmup: int = 5) -> bool:

    if not _CV2:
        return False
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return False
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return False
    return bool(np.mean(frame) > 8)


def _detect_camera_index() -> int:

    backend = _cv2_backend()
    print("[Vision] 🔍 Auto-detecting camera...")
    for idx in range(6):
        if _probe_camera(idx, backend):
            print(f"[Vision] ✅ Camera found at index {idx}")
            _save_config_key("camera_index", idx)
            return idx
        print(f"[Vision] ⚠️  Camera index {idx}: no usable frame")

    print("[Vision] ⚠️  No camera found — defaulting to index 0")
    _save_config_key("camera_index", 0)
    return 0


def _get_camera_index() -> int:
    cfg = _load_config()
    if "camera_index" in cfg:
        return int(cfg["camera_index"])
    return _detect_camera_index()


def _capture_camera() -> tuple[bytes, str]:
    if not _CV2:
        raise RuntimeError("OpenCV (cv2) is not installed. Run: pip install opencv-python")

    index   = _get_camera_index()
    backend = _cv2_backend()
    cap     = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        raise RuntimeError(f"Camera index {index} could not be opened.")

    for _ in range(10):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Camera returned no frame.")

    if _PIL:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    return buf.tobytes(), "image/jpeg"

class _VisionSession:
    def __init__(self):
        self._loop:       Optional[asyncio.AbstractEventLoop] = None
        self._thread:     Optional[threading.Thread]          = None
        self._session                                          = None
        self._out_queue:  Optional[asyncio.Queue]             = None
        self._audio_in:   Optional[asyncio.Queue]             = None
        self._ready_evt:  threading.Event                     = threading.Event()
        self._player                                           = None
        self._lock:       threading.Lock                       = threading.Lock()

    def start(self, player=None, timeout: float = 25.0) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                if player is not None:
                    self._player = player
                return
            self._player = player
            self._thread = threading.Thread(
                target=self._run_event_loop,
                daemon=True,
                name="VisionSessionThread",
            )
            self._thread.start()

        if not self._ready_evt.wait(timeout=timeout):
            raise RuntimeError(f"Vision session did not connect within {timeout}s.")
        print("[Vision] ✅ Session ready")

    def analyze(self, image_bytes: bytes, mime_type: str, user_text: str) -> None:
        if not self._loop or not self._out_queue:
            print("[Vision] ⚠️  Session not started — dropping request")
            return
        asyncio.run_coroutine_threadsafe(
            self._out_queue.put((image_bytes, mime_type, user_text)),
            self._loop,
        )

    def is_ready(self) -> bool:
        return self._session is not None

    def _run_event_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._session_loop())

    async def _session_loop(self) -> None:
        self._out_queue = asyncio.Queue(maxsize=30)
        self._audio_in  = asyncio.Queue()

        client = genai.Client(api_key=_get_api_key(), http_options={"api_version": "v1beta"})
        config = gtypes.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            system_instruction=_SYSTEM_PROMPT,
            speech_config=gtypes.SpeechConfig(
                voice_config=gtypes.VoiceConfig(
                    prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
            session_resumption=gtypes.SessionResumptionConfig(),
            realtime_input_config=gtypes.RealtimeInputConfig(
                automatic_activity_detection=gtypes.AutomaticActivityDetection(
                    start_of_speech_sensitivity=gtypes.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=gtypes.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=250,
                    prefix_padding_ms=150,
                ),
                activity_handling=gtypes.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                turn_coverage=gtypes.TurnCoverage.TURN_INCLUDES_ALL_INPUT,
            ),
        )

        backoff = 2.0
        while True:
            try:
                print("[Vision] 🔌 Connecting...")
                async with client.aio.live.connect(
                    model=_LIVE_MODEL, config=config
                ) as session:
                    self._session = session
                    self._ready_evt.set()
                    backoff = 2.0  
                    print("[Vision] ✅ Connected")

                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._send_loop())
                        tg.create_task(self._recv_loop())
                        tg.create_task(self._play_loop())

            except* Exception as eg:
                for exc in eg.exceptions:
                    print(f"[Vision] ⚠️  Session error: {exc}")
            finally:
                self._session = None
                self._ready_evt.clear()

            print(f"[Vision] 🔄 Reconnecting in {backoff:.0f}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 30.0)
            self._ready_evt.set()  

    async def _send_loop(self) -> None:
        while True:
            image_bytes, mime_type, user_text = await self._out_queue.get()
            if not self._session:
                print("[Vision] ⚠️  No session — dropping image")
                continue
            try:
                b64 = base64.b64encode(image_bytes).decode("ascii")
                await self._session.send_client_content(
                    turns={
                        "parts": [
                            {"inline_data": {"mime_type": mime_type, "data": b64}},
                            {"text": user_text},
                        ]
                    },
                    turn_complete=True,
                )
                print(f"[Vision] 📤 Sent {len(image_bytes):,} bytes — '{user_text[:60]}'")
            except Exception as e:
                print(f"[Vision] ⚠️  Send error: {e}")

    async def _recv_loop(self) -> None:
        transcript: list[str] = []
        try:
            async for response in self._session.receive():
                if response.data:
                    await self._audio_in.put(response.data)

                sc = response.server_content
                if not sc:
                    continue

                if sc.output_transcription and sc.output_transcription.text:
                    chunk = sc.output_transcription.text.strip()
                    if chunk:
                        transcript.append(chunk)

                if sc.turn_complete:
                    if transcript and self._player:
                        full = re.sub(r"\s+", " ", " ".join(transcript)).strip()
                        if full:
                            self._player.write_log(f"Jarvis: {full}")
                            print(f"[Vision] 💬 {full}")
                    transcript = []

        except Exception as e:
            print(f"[Vision] ⚠️  Recv error: {e}")
            raise  

    async def _play_loop(self) -> None:
        stream = sd.RawOutputStream(
            samplerate=_RECEIVE_SAMPLE_RATE,
            channels=_CHANNELS,
            dtype="int16",
            blocksize=_CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self._audio_in.get()
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[Vision] ❌ Play error: {e}")
            raise
        finally:
            stream.stop()
            stream.close()

_session      = _VisionSession()
_session_lock = threading.Lock()
_session_up   = False


def _ensure_session(player=None) -> None:
    global _session_up
    with _session_lock:
        if not _session_up:
            _session.start(player=player)
            _session_up = True
        elif player is not None:
            _session._player = player


def screen_process(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> bool:

    params    = parameters or {}
    user_text = (params.get("text") or params.get("user_text") or "").strip()
    angle     = params.get("angle", "screen").lower().strip()

    if not user_text:
        print("[Vision] ⚠️  No question provided — aborting")
        return False

    print(f"[Vision] ▶ angle={angle!r}  question='{user_text[:80]}'")

    try:
        _ensure_session(player=player)
    except Exception as e:
        print(f"[Vision] ❌ Could not start session: {e}")
        return False

    try:
        if angle == "camera":
            image_bytes, mime_type = _capture_camera()
            print(f"[Vision] 📷 Camera: {len(image_bytes):,} bytes")
        else:
            image_bytes, mime_type = _capture_screen()
            print(f"[Vision] 🖥️  Screen: {len(image_bytes):,} bytes")
    except Exception as e:
        print(f"[Vision] ❌ Capture error: {e}")
        return False

    _session.analyze(image_bytes, mime_type, user_text)
    return True


def warmup_session(player=None) -> None:
    try:
        _ensure_session(player=player)
    except Exception as e:
        print(f"[Vision] Warmup failed: {e}")
    # GPU detection
    try:
        import torch
        if torch.cuda.is_available():
            print(f"[GPU] CUDA available: {torch.cuda.get_device_name(0)}")
            _ = torch.zeros(1).cuda()  # warmup
        else:
            print("[GPU] CUDA not available, using CPU")
    except ImportError:
        print("[GPU] PyTorch not installed")


# ---- UI Element Detection (Phase 2: Windows UI Automation) ----


def _walk_elements(control, elements: list, depth: int, max_depth: int):
    if depth > max_depth:
        return
    try:
        name = (control.Name or "").strip()
        ct = control.ControlType
        from uiautomation import ControlType

        type_map = {
            ControlType.ButtonControl: "button",
            ControlType.EditControl: "input",
            ControlType.HyperlinkControl: "link",
            ControlType.ComboBoxControl: "input",
            ControlType.CheckBoxControl: "button",
            ControlType.RadioButtonControl: "button",
            ControlType.TabItemControl: "button",
            ControlType.MenuItemControl: "button",
            ControlType.ListItemControl: "button",
            ControlType.TreeItemControl: "button",
        }
        ctype = type_map.get(ct, "button" if ct not in (ControlType.PaneControl, ControlType.WindowControl) else "")
        if ctype and name:
            rect = control.BoundingRectangle
            elements.append({
                "name": name,
                "type": ctype,
                "bbox": [rect.left, rect.top, rect.right, rect.bottom],
            })
        for child in control.GetChildren():
            _walk_elements(child, elements, depth + 1, max_depth)
    except Exception:
        pass


def detect_ui_elements(angle: str = "screen") -> list[dict]:
    """Use Windows UI Automation to enumerate clickable elements."""
    import uiautomation as auto

    elements = []
    try:
        root = auto.GetRootControl()
        for window in root.GetChildren():
            if not window.Name:
                continue
            _walk_elements(window, elements, 0, 4)
    except Exception as e:
        return [{"error": f"UI detection failed: {e}"}]
    return elements


def _collect_names(control, names: list, depth: int, max_depth: int):
    if depth > max_depth:
        return
    try:
        if control.Name:
            names.append(control.Name.strip()[:60])
        for child in control.GetChildren():
            _collect_names(child, names, depth + 1, max_depth)
    except Exception:
        pass


def describe_current_view(angle: str = "screen") -> str:
    """Return a semantic description of what is currently on screen via Windows UI Automation."""
    import uiautomation as auto

    try:
        root = auto.GetRootControl()
        parts = []
        for window in root.GetChildren():
            if not window.Name:
                continue
            line = f"Window: {window.Name}"
            child_names = []
            _collect_names(window, child_names, 0, 2)
            if child_names:
                line += f" — contains: {', '.join(child_names[:10])}"
            parts.append(line)
        return "\n".join(parts[:5]) if parts else "No windows detected."
    except Exception as e:
        return f"Description failed: {e}"


def _ua_match_score(target: str, candidate: str) -> float:
    if target == candidate:
        return 1.0
    if target in candidate:
        return 0.9 + (len(target) / max(len(candidate), 1)) * 0.1
    t_words = set(target.split())
    c_words = set(candidate.split())
    if t_words and c_words:
        return len(t_words & c_words) / len(t_words) * 0.8
    return 0.0


def vision_find_and_click(target_description: str, angle: str = "screen") -> str:
    """Find a UI element by description via Windows UI Automation and return its coordinates."""
    import uiautomation as auto

    target_lower = target_description.lower().strip()
    try:
        root = auto.GetRootControl()
        best = (None, 0.0)

        def _search(control, depth=0, max_depth=5):
            nonlocal best
            if depth > max_depth:
                return
            try:
                name = (control.Name or "").strip()
                if name:
                    score = _ua_match_score(target_lower, name.lower())
                    if score > best[1]:
                        best = (control, score)
                for child in control.GetChildren():
                    _search(child, depth + 1, max_depth)
            except Exception:
                pass

        _search(root)
        ctrl = best[0]
        if ctrl and ctrl.BoundingRectangle:
            rect = ctrl.BoundingRectangle
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
            return json.dumps({
                "found": True,
                "name": ctrl.Name or "",
                "type": str(ctrl.ControlType),
                "x": cx,
                "y": cy,
                "bbox": [rect.left, rect.top, rect.right, rect.bottom],
            })
        return json.dumps({"found": False, "reason": f"No element matches '{target_description}'"})
    except Exception as e:
        return json.dumps({"found": False, "error": str(e)})


def vision_navigate_tool(parameters: dict, player=None) -> str:
    """Find and click a UI element by description using Windows UI Automation."""
    target = parameters.get("target", "")
    angle = parameters.get("angle", "screen")
    if not target:
        return "No target specified for vision navigation."
    result = vision_find_and_click(target, angle)
    data = json.loads(result) if isinstance(result, str) else result
    if data.get("found"):
        import pyautogui

        pyautogui.click(data["x"], data["y"])
        return f"Clicked on '{data['name']}' at ({data['x']}, {data['y']})"
    return f"Could not find '{target}' on screen. Details: {data.get('reason', data.get('error', 'unknown'))}"

if __name__ == "__main__":
    print("[TEST] screen_processor.py")
    print("=" * 52)
    mode = input("angle — screen / camera (default: screen): ").strip().lower() or "screen"
    q    = input("Question (Enter = default): ").strip() or "What do you see? Be brief."

    t0 = time.perf_counter()
    warmup_session()
    print(f"Session ready in {time.perf_counter()-t0:.2f}s\n")

    t1 = time.perf_counter()
    ok = screen_process({"angle": mode, "text": q})
    print(f"Queued in {time.perf_counter()-t1:.3f}s — waiting for audio...")
    time.sleep(10)
    print("Done." if ok else "Failed.")
