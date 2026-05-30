"""MARK XL — Auto-restart watchdog launcher.
Wraps main.py and restarts it if it crashes unexpectedly.
Usage:  python start.py
"""
import sys
import subprocess
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
MAIN_SCRIPT = BASE / "main.py"
LOG_FILE = BASE / "crash_log.txt"
MAX_RESTARTS = 10
RESTART_WINDOW = 300  # seconds — resets counter after 5 min uptime


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    if not MAIN_SCRIPT.exists():
        print(f"ERROR: {MAIN_SCRIPT} not found")
        sys.exit(1)

    restarts = 0
    window_start = time.time()

    print(f"MARK XL Watchdog — watching {MAIN_SCRIPT.name}")
    print(f"PID: {__import__('os').getpid()}")
    print(f"Max restarts: {MAX_RESTARTS} per {RESTART_WINDOW}s window")
    print("Press Ctrl+C to stop.\n")

    while True:
        log(f"Starting {MAIN_SCRIPT.name} ...")
        try:
            proc = subprocess.Popen(
                [sys.executable, str(MAIN_SCRIPT)] + sys.argv[1:],
                cwd=str(BASE),
                stdout=None,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait with timeout — if it exits quickly, treat as crash
            try:
                ret = proc.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                log("Uptime > 1 hour — resetting restart counter")
                restarts = 0
                window_start = time.time()
                proc.wait()

            # Check stderr for crash info
            if proc.returncode != 0:
                restarts += 1
                log(f"Exit code {proc.returncode} (restart #{restarts})")
                # Print last lines of stderr
                leftover = proc.stderr
                if leftover:
                    stderr_lines = leftover.read()
                    for line in stderr_lines.split("\n")[-10:]:
                        if line.strip():
                            log(f"  STDERR: {line.strip()}")
            else:
                log("Clean exit — shutting down watchdog")
                break

            # Rate limit restarts
            elapsed = time.time() - window_start
            if elapsed > RESTART_WINDOW:
                log(f"Resetting restart counter ({elapsed:.0f}s elapsed)")
                restarts = 0
                window_start = time.time()

            if restarts >= MAX_RESTARTS:
                log(f"FATAL: {MAX_RESTARTS} restarts in {RESTART_WINDOW}s — giving up")
                break

            time.sleep(2)

        except KeyboardInterrupt:
            log("Watchdog stopped by user")
            break
        except Exception as e:
            log(f"Watchdog error: {e}")
            break


if __name__ == "__main__":
    main()
