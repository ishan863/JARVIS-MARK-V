"""
remote_manager.py — Central coordinator for iOS remote control.

Manages:
  - FastAPI/WebSocket server lifecycle (port 5000)
  - PIN + QR code generation for pairing
  - Connected device registry
  - Bidirectional message routing between phone and JarvisLive
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import random
import socket
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from fastapi.websockets import WebSocket


def _get_local_ip() -> str:
    """Get the LAN/WiFi IP — works for both Ethernet and WiFi on same router."""
    best = "127.0.0.1"
    try:
        # Primary: route to 8.8.8.8 — picks the interface used for internet
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        best = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # If we only got loopback, enumerate all interfaces
    if best.startswith("127."):
        try:
            import socket as _s
            hostname = _s.gethostname()
            for addr in _s.getaddrinfo(hostname, None, _s.AF_INET):
                ip = addr[4][0]
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    best = ip
                    break
        except Exception:
            pass
    return best


class RemoteManager:
    """Singleton that owns the remote HTTP/WebSocket server and device state."""

    def __init__(self):
        self.pin: str = ""
        self.ip: str = _get_local_ip()
        self.port: int = 5000
        self.running: bool = False

        # Connected WebSocket clients: {ws: {"name": str, "paired": bool}}
        self._clients: dict[Any, dict] = {}
        self._clients_lock = threading.Lock()

        # Reference to JarvisLive (set after JARVIS starts)
        self._jarvis = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        # Uvicorn event loop (set on server startup)
        self._uvicorn_loop: Optional[asyncio.AbstractEventLoop] = None

        self._server_thread: Optional[threading.Thread] = None
        self._scheme: str = "https"

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def set_jarvis(self, jarvis, loop: asyncio.AbstractEventLoop):
        """Called from JarvisLive after the session is established."""
        self._jarvis = jarvis
        self._main_loop = loop

    def start(self) -> str:
        """Start the FastAPI server in a background thread. Returns URL."""
        if self.running:
            return f"{self._scheme}://{self.ip}:{self.port}"
        # Refresh IP in case network changed
        self.ip = _get_local_ip()
        self.pin = f"{random.randint(1000, 9999)}"
        self.running = True
        self._server_thread = threading.Thread(
            target=self._run_uvicorn, daemon=True, name="RemoteServer"
        )
        self._server_thread.start()
        print(f"[Remote] Server starting on {self._scheme}://{self.ip}:{self.port}  PIN={self.pin}")
        return f"{self._scheme}://{self.ip}:{self.port}"

    def stop(self):
        self.running = False
        if hasattr(self, '_uvicorn_server'):
            self._uvicorn_server.should_exit = True

    def get_status(self) -> dict:
        with self._clients_lock:
            devices = [
                {"name": v.get("name", "Unknown"), "paired": v.get("paired", False)}
                for v in self._clients.values()
            ]
        return {
            "running": self.running,
            "ip": self.ip,
            "port": self.port,
            "pin": self.pin,
            "url": f"http://{self.ip}:{self.port}",
            "devices": devices,
        }

    def get_qr_pixmap(self):
        """
        Generate QR code as QPixmap for the Qt dashboard.
        The QR encodes the full URL including PIN so iOS Camera auto-opens
        Safari and the page auto-connects without manual PIN entry.
        """
        try:
            import qrcode
            from PIL import Image
            from PyQt6.QtGui import QPixmap, QImage

            url = f"{self._scheme}://{self.ip}:{self.port}/?pin={self.pin}"
            qr = qrcode.QRCode(
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=7,
                border=3,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            data = buf.read()
            qimg = QImage.fromData(data)
            return QPixmap.fromImage(qimg)
        except Exception as e:
            print(f"[Remote] QR pixmap failed: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Broadcast helpers (called from main JARVIS loop)
    # ------------------------------------------------------------------ #

    def broadcast_text(self, text: str):
        """Send AI text response to all paired phone clients."""
        self._broadcast_sync({"type": "ai_text", "data": text})

    def broadcast_audio(self, audio_b64: str):
        """Send AI audio chunk (base64 MP3) to all paired phone clients."""
        self._broadcast_sync({"type": "ai_audio", "data": audio_b64})

    def broadcast_log(self, text: str):
        """Forward a log line to all paired phone clients."""
        self._broadcast_sync({"type": "log", "data": text})

    def _broadcast_sync(self, msg: dict):
        if not self._uvicorn_loop or not self._clients:
            return
        asyncio.run_coroutine_threadsafe(
            self._broadcast_async(msg), self._uvicorn_loop
        )

    async def _broadcast_async(self, msg: dict):
        dead = []
        with self._clients_lock:
            clients = list(self._clients.items())
        for ws, info in clients:
            if not info.get("paired"):
                continue
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        if dead:
            with self._clients_lock:
                for ws in dead:
                    self._clients.pop(ws, None)

    # ------------------------------------------------------------------ #
    #  Message routing: phone → JARVIS
    # ------------------------------------------------------------------ #

    def route_text_to_jarvis(self, text: str):
        """Send a text message from phone to the JARVIS Live session."""
        if not self._jarvis or not self._main_loop or not self._jarvis.session:
            return
        from google.genai import types
        asyncio.run_coroutine_threadsafe(
            self._jarvis.session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=True
            ),
            self._main_loop
        )

    def route_audio_to_jarvis(self, pcm_bytes: bytes):
        """Send raw PCM audio from phone to the JARVIS Live session."""
        if not self._jarvis or not self._main_loop or not self._jarvis.session:
            return
        from google.genai import types as gtypes
        async def _send():
            self._jarvis._phone_audio_active = True
            await self._jarvis.session.send_realtime_input(
                audio=gtypes.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
            )
        asyncio.run_coroutine_threadsafe(_send(), self._main_loop)

    def route_audio_chunk(self, pcm_bytes: bytes):
        """Send a streaming audio chunk from phone to Gemini (real-time)."""
        if not self._jarvis or not self._main_loop or not self._jarvis.session:
            return
        from google.genai import types as gtypes
        async def _send():
            self._jarvis._phone_audio_active = True
            await self._jarvis.session.send_realtime_input(
                audio=gtypes.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
            )
        asyncio.run_coroutine_threadsafe(_send(), self._main_loop)

    def route_audio_end(self):
        """Signal Gemini that the phone user stopped speaking (turn_complete)."""
        if not self._jarvis or not self._main_loop or not self._jarvis.session:
            return
        async def _send():
            await self._jarvis.session.send_client_content(turn_complete=True)
        asyncio.run_coroutine_threadsafe(_send(), self._main_loop)

    def broadcast_audio_response(self, wav_b64: str):
        """Send AI voice audio (WAV base64) to all paired phone clients."""
        self._broadcast_sync({"type": "ai_audio", "data": wav_b64, "format": "audio/wav"})

    def broadcast_input_transcript(self, text: str):
        """Send live input transcription to all paired phone clients."""
        self._broadcast_sync({"type": "ai_input_transcript", "data": text})

    def broadcast_file_push(self, file_name: str, file_b64: str):
        """Send a file (name + base64 data) to all paired phone clients."""
        self._broadcast_sync({"type": "file_push", "name": file_name, "data": file_b64})

    def execute_tool(self, tool_name: str, params: dict) -> str:
        """Execute a JARVIS tool from the phone and return the result."""
        if not self._jarvis or not self._main_loop:
            return "JARVIS not connected."
        from core.orchestrator import orchestrator, ToolContext

        loop = self._main_loop

        async def _run():
            ctx = ToolContext(ui=self._jarvis.ui, speak=self._jarvis.speak, loop=loop)
            try:
                result = await orchestrator.route(tool_name, params, ctx)
                return str(result) if result else "Done."
            except Exception as e:
                return f"Tool error: {e}"

        future = asyncio.run_coroutine_threadsafe(_run(), loop)
        try:
            return future.result(timeout=30)
        except Exception as e:
            return f"Execution timeout: {e}"

    def take_screenshot(self) -> Optional[str]:
        """Capture desktop screenshot, return base64 JPEG string."""
        try:
            import mss
            from PIL import Image

            with mss.mss() as sct:
                monitor = sct.monitors[1]
                sshot = sct.grab(monitor)
                img = Image.frombytes("RGB", sshot.size, sshot.bgra, "raw", "BGRX")
                w, h = img.size
                # Scale to max 1280px wide for mobile bandwidth
                scale = min(1.0, 1280 / w)
                if scale < 1.0:
                    img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            print(f"[Remote] Screenshot failed: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Internal — uvicorn thread
    # ------------------------------------------------------------------ #

    def _ensure_ssl_cert(self) -> tuple[str, str]:
        """Generate a self-signed cert so mobile mic (getUserMedia) works on iOS/Android."""
        import datetime as _dt
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        ssl_dir = Path(__file__).resolve().parent.parent / ".ssl"
        ssl_dir.mkdir(parents=True, exist_ok=True)
        cert_path = ssl_dir / "cert.pem"
        key_path = ssl_dir / "key.pem"

        if cert_path.exists() and key_path.exists():
            return str(cert_path), str(key_path)

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subj = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "JARVIS Remote")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subj)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_dt.datetime.now(tz=_dt.timezone.utc))
            .not_valid_after(_dt.datetime.now(tz=_dt.timezone.utc) + _dt.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("192.168.29.59")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        print(f"[Remote] Self-signed SSL cert generated (10 yr validity)")
        return str(cert_path), str(key_path)

    def _run_uvicorn(self):
        try:
            import uvicorn
            from server.remote_server import build_app
            app = build_app(self)
            try:
                ssl_cert, ssl_key = self._ensure_ssl_cert()
                kw = dict(ssl_certfile=ssl_cert, ssl_keyfile=ssl_key)
                scheme = "https"
            except Exception as e:
                print(f"[Remote] SSL setup failed ({e}), falling back to HTTP")
                kw = {}
                scheme = "http"
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=self.port,
                log_level="warning",
                access_log=False,
                **kw,
            )
            self._scheme = scheme
            self._uvicorn_server = uvicorn.Server(config)
            self._uvicorn_server.run()
        except Exception as e:
            print(f"[Remote] Server error: {e}")
            self.running = False


# Global singleton
remote_manager = RemoteManager()
