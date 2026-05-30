import asyncio
import threading
import time
import traceback
from typing import Any, Callable, Coroutine, Optional


class ToolContext:
    """Context passed to every tool handler."""
    def __init__(self, ui, speak: Callable, loop: asyncio.AbstractEventLoop):
        self.ui = ui
        self.speak = speak
        self.loop = loop


class MiddlewareResult:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error


class Middleware:
    async def before(self, name: str, args: dict, context: ToolContext) -> Optional[MiddlewareResult]:
        return None

    async def after(self, name: str, args: dict, context: ToolContext, result: Any, duration: float):
        pass

    async def error(self, name: str, args: dict, context: ToolContext, error: Exception) -> Optional[MiddlewareResult]:
        return None


class TimingMiddleware(Middleware):
    def __init__(self):
        self.times: dict[str, list[float]] = {}

    async def after(self, name, args, context, result, duration):
        self.times.setdefault(name, []).append(duration)

    def get_stats(self):
        stats = {}
        for name, times in self.times.items():
            avg = sum(times) / len(times)
            stats[name] = {"count": len(times), "avg_ms": round(avg * 1000, 1)}
        return stats


class RetryMiddleware(Middleware):
    def __init__(self, max_retries=1):
        self.max_retries = max_retries

    async def error(self, name, args, context, error):
        if self.max_retries > 0:
            self.max_retries -= 1
            return MiddlewareResult(result=None)  # signal retry
        return None


class ErrorLogMiddleware(Middleware):
    async def error(self, name, args, context, error):
        traceback.print_exc()
        context.ui.write_log(f"ERR: {name} — {str(error)[:120]}")
        return None


ToolHandler = Callable[[dict, ToolContext], Any]


class Orchestrator:
    def __init__(self):
        self._registry: dict[str, ToolHandler] = {}
        self._middleware: list[Middleware] = []
        self.timing = TimingMiddleware()
        self._use(self.timing)
        self._use(RetryMiddleware(max_retries=1))
        self._use(ErrorLogMiddleware())

    def register(self, name: str, handler: ToolHandler):
        self._registry[name] = handler

    def _use(self, middleware: Middleware):
        self._middleware.append(middleware)

    def get_handler(self, name: str) -> Optional[ToolHandler]:
        return self._registry.get(name)

    async def route(self, name: str, args: dict, context: ToolContext) -> Any:
        if name not in self._registry:
            return f"Unknown tool: {name}"

        handler = self._registry[name]
        last_error = None
        for attempt in range(3):
            try:
                for mw in self._middleware:
                    mw_result = await mw.before(name, args, context)
                    if mw_result is not None:
                        if mw_result.error:
                            raise mw_result.error
                        return mw_result.result

                start = time.perf_counter()
                result = handler(args, context)
                if asyncio.iscoroutine(result):
                    result = await result
                duration = time.perf_counter() - start

                for mw in self._middleware:
                    await mw.after(name, args, context, result, duration)

                return result

            except Exception as e:
                last_error = e
                retry = False
                for mw in self._middleware:
                    mw_result = await mw.error(name, args, context, e)
                    if mw_result is not None and mw_result.result is None:
                        retry = True
                        break
                if not retry:
                    break
                await asyncio.sleep(0.5 * (attempt + 1))

        raise last_error or RuntimeError(f"Tool '{name}' failed after retries")


orchestrator = Orchestrator()


def _phone_broadcast(file_name: str, file_b64: str):
    """Broadcast a file to all paired phone clients. Safe to call from any thread."""
    try:
        from core.remote_manager import remote_manager
        if remote_manager:
            remote_manager.broadcast_file_push(file_name, file_b64)
    except Exception:
        pass


def register_actions():
    from actions.file_processor import file_processor
    from actions.flight_finder import flight_finder
    from actions.open_app import open_app
    from actions.weather_report import weather_action
    from actions.send_message import send_message
    from actions.reminder import reminder
    from actions.computer_settings import computer_settings
    from actions.screen_processor import screen_process, vision_navigate_tool
    from actions.youtube_video import youtube_video
    from actions.desktop import desktop_control
    from actions.browser_control import browser_control
    from actions.file_controller import file_controller
    from actions.code_helper import code_helper
    from actions.dev_agent import dev_agent
    from actions.web_search import web_search as web_search_action
    from actions.computer_control import computer_control
    from actions.game_updater import game_updater
    from actions.crypto_data import crypto_data
    from actions.browser_playwright import browser_playwright_action
    from actions.vscode_controller import vscode_controller
    from actions.browser_agent import browser_agent
    from actions.browser_v2 import browser_ai_task
    from actions.excel_reporter import excel_report
    from actions.data_pipeline import data_pipeline

    async def _run(fn, args, context, extra=None):
        kwargs = {"parameters": args, "player": context.ui}
        if extra:
            kwargs.update(extra)
        return await context.loop.run_in_executor(None, lambda: fn(**kwargs))

    orchestrator.register("open_app", lambda a, ctx: _run(open_app, a, ctx))
    orchestrator.register("weather_report", lambda a, ctx: _run(weather_action, a, ctx))
    orchestrator.register("browser_control", lambda a, ctx: _run(browser_control, a, ctx))
    orchestrator.register("file_controller", lambda a, ctx: _run(
        file_controller, a, ctx,
        {"loop": ctx.loop, "broadcast_fn": _phone_broadcast}
    ))
    orchestrator.register("send_message", lambda a, ctx: _run(send_message, a, ctx, {"response": None, "session_memory": None}))
    orchestrator.register("reminder", lambda a, ctx: _run(reminder, a, ctx, {"response": None}))
    orchestrator.register("youtube_video", lambda a, ctx: _run(youtube_video, a, ctx, {"response": None}))
    orchestrator.register("computer_settings", lambda a, ctx: _run(computer_settings, a, ctx, {"response": None}))
    orchestrator.register("desktop_control", lambda a, ctx: _run(desktop_control, a, ctx))
    orchestrator.register("code_helper", lambda a, ctx: _run(code_helper, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("dev_agent", lambda a, ctx: _run(dev_agent, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("web_search", lambda a, ctx: _run(web_search_action, a, ctx))
    orchestrator.register("file_processor", lambda a, ctx: _run(file_processor, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("computer_control", lambda a, ctx: _run(computer_control, a, ctx))
    orchestrator.register("game_updater", lambda a, ctx: _run(game_updater, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("flight_finder", lambda a, ctx: _run(flight_finder, a, ctx))
    orchestrator.register("crypto_data", lambda a, ctx: _run(crypto_data, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("browser_playwright", lambda a, ctx: _run(browser_playwright_action, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("vscode_controller", lambda a, ctx: _run(vscode_controller, a, ctx))
    orchestrator.register("vision_navigate", lambda a, ctx: _run(vision_navigate_tool, a, ctx))
    orchestrator.register("browser_agent", lambda a, ctx: _run(browser_agent, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("browser_ai", lambda a, ctx: _run(browser_ai_task, a, ctx, {"speak": ctx.speak}))
    orchestrator.register("excel_report", lambda a, ctx: _run(excel_report, a, ctx))
    orchestrator.register("data_pipeline", lambda a, ctx: _run(data_pipeline, a, ctx))

    # clipboard_manager
    from actions.clipboard_manager import clipboard_manager
    orchestrator.register("clipboard_manager", lambda a, ctx: _run(clipboard_manager, a, ctx))

    # calculator
    from actions.calculator import calculator
    orchestrator.register("calculator", lambda a, ctx: _run(calculator, a, ctx))

    # media_control
    from actions.media_control import media_control
    orchestrator.register("media_control", lambda a, ctx: _run(media_control, a, ctx))

    # notification
    from actions.notification import notification
    orchestrator.register("notification", lambda a, ctx: _run(notification, a, ctx))

    # screen_process runs in a thread (special — vision speaks directly)
    def _screen_process_wrapper(args, ctx):
        threading.Thread(
            target=screen_process,
            kwargs={"parameters": args, "response": None,
                    "player": ctx.ui, "session_memory": None},
            daemon=True
        ).start()
        return "Vision module activated. Stay completely silent — vision module will speak directly."

    orchestrator.register("screen_process", _screen_process_wrapper)

    # save_memory — handled inline
    from memory.memory_manager import update_memory

    def _save_memory(args, ctx):
        category = args.get("category", "notes")
        key = args.get("key", "")
        value = args.get("value", "")
        if key and value:
            update_memory({category: {key: {"value": value}}})
        return {"result": "ok", "silent": True}

    orchestrator.register("save_memory", _save_memory)

    # memory_search — semantic recall from ChromaDB
    from memory.memory_manager import semantic_db, load_memory, format_memory_for_prompt

    def _memory_search(args, ctx):
        query = args.get("query", "").strip()
        category = args.get("category", "").strip()
        if not query:
            facts = load_memory()
            total = sum(len(v) for v in facts.values() if isinstance(v, dict))
            return f"Memory has {total} entries across {len(facts)} categories."
        results = semantic_db.search_facts(query, n_results=5)
        if not results:
            return f"No memory found for: {query}"
        lines = [f"Memory results for '{query}':"]
        for r in results:
            lines.append(f"  - {r}")
        return "\n".join(lines)

    orchestrator.register("memory_search", _memory_search)

    # agent_task — submit to task queue
    def _agent_task(args, ctx):
        from agent.task_queue import get_queue, TaskPriority
        priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
        priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
        task_id = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=ctx.speak)
        return f"Task started (ID: {task_id})."

    orchestrator.register("agent_task", _agent_task)

    # shutdown_jarvis
    def _shutdown(args, ctx):
        ctx.ui.write_log("SYS: Shutdown requested.")
        ctx.speak("Goodbye, sir.")
        import os
        def _do_exit():
            import time
            time.sleep(1)
            os._exit(0)
        threading.Thread(target=_do_exit, daemon=True).start()
        return "Shutting down."

    orchestrator.register("shutdown_jarvis", _shutdown)

    # daily_brief — agent activity summary
    from core.agent_tracker import daily_brief
    orchestrator.register("daily_brief", lambda a, ctx: _run(daily_brief, a, ctx))
