import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _find_vscode() -> str:
    user_home = os.path.expanduser("~")
    candidates = [
        os.path.join(user_home, r"AppData\Local\Programs\Microsoft VS Code\bin\code.cmd"),
        os.path.join(user_home, r"AppData\Local\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files (x86)\Microsoft VS Code\bin\code.cmd",
        "code",
        "code.cmd",
        "code-insiders",
    ]
    for c in candidates:
        try:
            proc = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                return c
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ""


def open_vscode(path: str = ".") -> str:
    code = _find_vscode()
    if not code:
        return "VS Code not found. Please install VS Code first."
    try:
        subprocess.Popen([code, os.path.abspath(path)], shell=False)
        return f"Opened VS Code at {path}"
    except Exception as e:
        return f"Failed to open VS Code: {e}"


def write_file(path: str, content: str) -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        code = _find_vscode()
        if code:
            subprocess.Popen([code, "--goto", f"{p.resolve()}:1"], shell=False)
        return f"File written to {path} and opened in VS Code"
    except Exception as e:
        return f"Failed to write file: {e}"


def run_command(command: str, cwd: str = ".") -> str:
    """Run a command using subprocess (VS Code CLI no longer supports --command flag)."""
    try:
        abs_cwd = os.path.abspath(cwd) if cwd != "." else os.getcwd()
        parts = command.split()
        if parts and parts[0].lower() == "python":
            parts[0] = sys.executable
        result = subprocess.run(
            parts,
            capture_output=True, text=True, timeout=30,
            cwd=abs_cwd,
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        output = out[:500] if out else ""
        if err:
            output += ("\n" + err[:300]) if output else err[:300]
        if not output:
            return f"Command completed with no output: {command}"
        return f"Ran: {command}\nOutput:\n{output}"
    except subprocess.TimeoutExpired:
        return f"Command timed out after 30s (long-running process): {command}"
    except Exception as e:
        return f"Failed to run command: {e}"


def get_terminal_output() -> str:
    return "Terminal output capture is available via VS Code extension API. Use manual check."


def open_file_at_line(path: str, line: int = 1) -> str:
    code = _find_vscode()
    if not code:
        return "VS Code not found. Please install VS Code first."
    try:
        p = os.path.abspath(path)
        subprocess.Popen([code, "--goto", f"{p}:{line}"], shell=False)
        return f"Opened {path} at line {line} in VS Code"
    except Exception as e:
        return f"Failed to open file: {e}"


def search_in_project(query: str, path: str = ".") -> str:
    code = _find_vscode()
    if not code:
        return "VS Code not found. Please install VS Code first."
    try:
        abs_path = os.path.abspath(path)
        # VS Code 1.122+ removed --command flag; use terminal-based search instead
        files = []
        for root, dirs, fnames in os.walk(abs_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
            for fname in fnames:
                if fname.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".md", ".txt")):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f, 1):
                                if query.lower() in line.lower():
                                    files.append(f"{fpath}:{i}: {line.strip()[:100]}")
                                    if len(files) >= 10:
                                        break
                    except Exception:
                        pass
                if len(files) >= 10:
                    break
            if len(files) >= 10:
                break
        if files:
            return f"Found {len(files)} matches for '{query}':\n" + "\n".join(files)
        return f"No matches found for '{query}' in {abs_path}"
    except Exception as e:
        return f"Failed to search: {e}"


def vscode_controller(parameters: dict, player=None) -> str:
    action = parameters.get("action", "open")
    path = parameters.get("path", ".")
    content = parameters.get("content", "")
    command = parameters.get("command", "")
    query = parameters.get("query", "")
    line = parameters.get("line", 1)

    if action == "open":
        return open_vscode(path)
    elif action == "write_file":
        return write_file(path, content)
    elif action == "run_command":
        return run_command(command, path)
    elif action == "open_at_line":
        return open_file_at_line(path, line)
    elif action == "search":
        return search_in_project(query, path)
    elif action == "terminal_output":
        return get_terminal_output()
    else:
        return f"Unknown vscode action: {action}"
