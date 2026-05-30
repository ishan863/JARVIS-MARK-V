"""Windows toast notifications for reminders, completions, and alerts."""
import subprocess
import time
from pathlib import Path


import xml.sax.saxutils as saxutils

def _send_toast(title: str, message: str, duration: int = 5):
    """Send a Windows toast notification using PowerShell."""
    safe_title = saxutils.escape(title)
    safe_message = saxutils.escape(message)
    ps_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName("text")
$textNodes.Item(0).AppendChild($template.CreateTextNode("{safe_title}")) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode("{safe_message}")) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("MARK XL").Show($toast)
'''
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=10
        )
    except Exception as e:
        print(f"[Toast] Failed: {e}")


def _is_scheduled_task_installed() -> bool:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-ScheduledTask -TaskName 'MARKXL_Startup' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty TaskName"],
            capture_output=True, text=True, timeout=5
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def _install_startup():
    """Register MARK XL to auto-start with Windows via scheduled task."""
    script_path = Path(__file__).resolve().parent.parent / "start.py"
    if not script_path.exists():
        script_path = Path(__file__).resolve().parent.parent / "main.py"
    ps_script = f'''
$action = New-ScheduledTaskAction -Execute "{script_path}"
$trigger = New-ScheduledTaskTrigger -AtLogon
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "MARKXL_Startup" -Action $action -Trigger $trigger -Principal $principal -Force
'''
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            return "Auto-start installed. MARK XL will start when you log in."
        return f"Failed: {r.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"


def _remove_startup():
    """Remove the auto-start scheduled task."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Unregister-ScheduledTask -TaskName 'MARKXL_Startup' -Confirm:$false"],
            capture_output=True, timeout=10
        )
        return "Auto-start removed."
    except Exception as e:
        return f"Failed: {e}"


def notification(parameters=None, player=None, **kwargs) -> str:
    params = parameters or {}
    action = params.get("action", "notify").strip().lower()

    if action == "notify":
        title = params.get("title", "MARK XL")
        message = params.get("message", "")
        duration = int(params.get("duration", 5))
        if not message:
            return "No message provided."
        _send_toast(title, message, duration)
        return f"Notification sent: {title}"

    if action == "startup_status":
        installed = _is_scheduled_task_installed()
        return f"Auto-start is {'installed' if installed else 'not installed'}."

    if action == "startup_install":
        return _install_startup()

    if action == "startup_remove":
        return _remove_startup()

    return f"Unknown action: {action}. Use: notify, startup_status, startup_install, startup_remove."
