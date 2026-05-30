"""Media control — Spotify, YouTube Music, and system media playback."""
import subprocess
import time
from pathlib import Path


def _powershell(cmd: str) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip()
    except Exception as e:
        return f""


def _find_spotify() -> bool:
    r = _powershell(
        'Get-Process -Name "Spotify" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'
    )
    return bool(r.strip())


def _find_ytmusic() -> bool:
    r = _powershell(
        'Get-Process -Name "chrome" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match "YouTube Music" } | Select-Object -ExpandProperty Id'
    )
    return bool(r.strip())


def _send_media_key(key: str):
    """Send media keys via PowerShell."""
    key_map = {
        "playpause": 179, "stop": 178, "next": 176, "previous": 177,
        "play": 179, "pause": 179,
    }
    code = key_map.get(key.lower())
    if code:
        _powershell(
            f"(New-Object -ComObject WScript.Shell).SendKeys([char]{code})"
        )


def _get_spotify_status() -> dict:
    """Try to get Spotify playback status."""
    try:
        ps_script = (
            'Add-Type -AssemblyName System.Windows.Forms; '
            "$mainWindow = [System.Windows.Forms.Application]::OpenForms | "
            "Where-Object { $_.Text -match 'Spotify' }; "
            "if ($mainWindow) { $mainWindow.Text } else { '' }"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=5
        )
        title = r.stdout.strip()
        if title and "Spotify" in title:
            title = title.replace("Spotify", "").replace("Free", "").strip().strip("- ")
            return {"playing": bool(title), "track": title or "Unknown"}
    except Exception:
        pass
    return {"playing": False, "track": ""}


def media_control(parameters=None, player=None, **kwargs) -> str:
    params = parameters or {}
    action = params.get("action", "status").strip().lower()

    spotify_running = _find_spotify()

    if action == "play":
        if not spotify_running:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command",
                 "Start-Process 'spotify:'"],
                shell=True
            )
            return "Launching Spotify..."
        _send_media_key("playpause")
        return "Playing."

    if action == "pause":
        _send_media_key("playpause")
        return "Paused."

    if action == "next":
        _send_media_key("next")
        return "Skipped to next track."

    if action == "previous":
        _send_media_key("previous")
        return "Went to previous track."

    if action == "stop":
        _send_media_key("stop")
        return "Stopped playback."

    if action == "status":
        if spotify_running:
            status = _get_spotify_status()
            if status["track"]:
                return f"Spotify is {'playing' if status['playing'] else 'paused'}. Current: {status['track']}"
            return "Spotify is running."
        return "No media player detected."

    if action == "launch":
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command",
             "Start-Process 'spotify:'"],
            shell=True
        )
        return "Launching Spotify..."

    return f"Unknown action: {action}. Use: play, pause, next, previous, stop, status, launch."
