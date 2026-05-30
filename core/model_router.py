import os
import time
from pathlib import Path

import google.genai as genai

try:
    from groq import Groq
except Exception:
    Groq = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from core.security import security


def get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


class ModelRouter:
    """
    Provider-aware router for text generation.
    Supports: gemini, groq, nvidia, openrouter, deepseek, local
    Currently active: gemini, groq, nvidia (all free)
    """

    PROVIDER_CONFIG = {
        "gemini": {
            "models": ["gemini-2.5-flash", "gemini-2.0-flash"],
            "cost_per_1k_out": 0.0,
            "premium": False,
            "free": True,
        },
        "groq": {
            "models": ["llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"],
            "cost_per_1k_out": 0.0,
            "premium": False,
            "free": True,
        },
        "nvidia": {
            "models": ["deepseek-ai/deepseek-v4-flash", "meta/llama-3.1-8b-instruct", "mistralai/mistral-7b-instruct-v0.3", "google/gemma-2-9b-it", "microsoft/phi-3-mini-4k-instruct"],
            "cost_per_1k_out": 0.0,
            "premium": False,
            "free": True,
        },
        "deepseek": {
            "models": ["deepseek-chat", "deepseek-coder"],
            "cost_per_1k_out": 0.00028,
            "premium": False,
            "free": False,
        },
        "openrouter": {
            "models": ["openai/gpt-4o-mini", "anthropic/claude-3-haiku"],
            "cost_per_1k_out": 0.00015,
            "premium": False,
            "free": False,
        },
        "local": {
            "models": ["local-model"],
            "cost_per_1k_out": 0.0,
            "premium": False,
            "free": True,
        },
    }

    # AGENT → MODEL MAPPING:
    # code_gen:           dev_agent, code_helper → NVIDIA DeepSeek V4 → DeepSeek → Gemini → Groq
    # code_review:        error_handler, code_helper refactor/self-fix → NVIDIA → Gemini → Groq
    # quick_chat:         general conversation → Groq (fastest) → Gemini → NVIDIA
    # vision:             screen_processor, browser_agent → Gemini (only vision-capable)
    # planning:           planner, dev_agent plan → Gemini → Groq → NVIDIA
    # web_search:         web_search → Groq → Gemini
    # summarization:      file_processor → Groq → Gemini → NVIDIA
    # reasoning:          error_handler, planner → Gemini → Groq → NVIDIA
    # creative:           general → Gemini → Groq → NVIDIA
    # default:            fallback → Gemini → Groq → NVIDIA → DeepSeek
    TASK_ROUTING = {
        "code_gen":       ["nvidia", "deepseek", "gemini", "groq"],
        "code_review":    ["nvidia", "gemini", "groq"],
        "quick_chat":     ["groq", "gemini", "nvidia"],
        "vision":         ["gemini"],
        "planning":       ["gemini", "groq", "nvidia"],
        "web_search":     ["groq", "gemini"],
        "summarization":  ["groq", "gemini", "nvidia"],
        "reasoning":      ["gemini", "groq", "nvidia"],
        "creative":       ["gemini", "groq", "nvidia"],
        "default":        ["gemini", "groq", "nvidia", "deepseek"],
    }

    def __init__(self):
        self.keys = security.decrypt_keys()
        self.clients = {}
        self.stats = {}  # provider -> {"calls": 0, "total_latency": 0.0, "errors": 0}
        self._init_clients()

    def _init_clients(self):
        gemini_key = self.keys.get("gemini_api_key", "").strip()
        if gemini_key:
            try:
                self.clients["gemini"] = genai.Client(api_key=gemini_key)
            except Exception:
                self.clients["gemini"] = None
        else:
            self.clients["gemini"] = None

        groq_key = self.keys.get("groq_api_key", "").strip()
        if groq_key and Groq is not None:
            try:
                self.clients["groq"] = Groq(api_key=groq_key)
            except Exception:
                self.clients["groq"] = None
        else:
            self.clients["groq"] = None

        if OpenAI is not None:
            nvidia_key = self.keys.get("nvidia_api_key", "").strip()
            if nvidia_key:
                try:
                    self.clients["nvidia"] = OpenAI(
                        base_url="https://integrate.api.nvidia.com/v1",
                        api_key=nvidia_key,
                    )
                except Exception:
                    self.clients["nvidia"] = None
            else:
                self.clients["nvidia"] = None

            openrouter_key = self.keys.get("openrouter_api_key", "").strip()
            if openrouter_key:
                try:
                    self.clients["openrouter"] = OpenAI(
                        base_url="https://openrouter.ai/api/v1",
                        api_key=openrouter_key,
                    )
                except Exception:
                    self.clients["openrouter"] = None
            else:
                self.clients["openrouter"] = None

            deepseek_key = self.keys.get("deepseek_api_key", "").strip()
            deepseek_base = self.keys.get("deepseek_base_url", "https://api.deepseek.com/v1").strip()
            if deepseek_key:
                try:
                    self.clients["deepseek"] = OpenAI(
                        base_url=deepseek_base,
                        api_key=deepseek_key,
                    )
                except Exception:
                    self.clients["deepseek"] = None
            else:
                self.clients["deepseek"] = None

            local_base = self.keys.get("local_llm_base_url", "").strip()
            local_key = self.keys.get("local_llm_api_key", "local").strip() or "local"
            if local_base:
                try:
                    self.clients["local"] = OpenAI(
                        base_url=local_base,
                        api_key=local_key,
                    )
                except Exception:
                    self.clients["local"] = None
            else:
                self.clients["local"] = None
        else:
            for p in ("nvidia", "openrouter", "deepseek", "local"):
                self.clients[p] = None

    def available_providers(self) -> list[str]:
        return [p for p, c in self.clients.items() if c is not None]

    def _record(self, provider: str, latency: float, error: bool = False):
        if provider not in self.stats:
            self.stats[provider] = {"calls": 0, "total_latency": 0.0, "errors": 0}
        self.stats[provider]["calls"] += 1
        self.stats[provider]["total_latency"] += latency
        if error:
            self.stats[provider]["errors"] += 1

    def _chat_completion(self, client, prompt: str, model: str) -> str:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
        )
        return response.choices[0].message.content

    def generate(self, prompt: str, provider: str = "gemini", model: str = "") -> str:
        p = (provider or "gemini").strip().lower()
        client = self.clients.get(p)
        if client is None:
            return f"Provider {p} not configured."

        if not model:
            model = self.PROVIDER_CONFIG.get(p, {}).get("models", [""])[0]

        start = time.perf_counter()
        try:
            if p == "gemini":
                response = client.models.generate_content(model=model, contents=prompt)
                result = response.text
            else:
                result = self._chat_completion(client, prompt, model)
            self._record(p, time.perf_counter() - start)
            return result
        except Exception as e:
            self._record(p, time.perf_counter() - start, error=True)
            return f"Error from {p}: {e}"

    def smart_route(self, prompt: str, task_type: str = "default", context: str = "") -> str:
        """Auto-select best provider based on task type. Returns the generated text."""
        route = self.TASK_ROUTING.get(task_type, self.TASK_ROUTING["default"])
        last_error = None

        for provider in route:
            client = self.clients.get(provider)
            if client is None:
                continue

            model = self.PROVIDER_CONFIG.get(provider, {}).get("models", [""])[0]
            start = time.perf_counter()
            try:
                if provider == "gemini":
                    response = client.models.generate_content(model=model, contents=prompt)
                    result = response.text
                else:
                    result = self._chat_completion(client, prompt, model)
                self._record(provider, time.perf_counter() - start)
                return result
            except Exception as e:
                self._record(provider, time.perf_counter() - start, error=True)
                last_error = e
                continue

        return f"All providers failed. Last error: {last_error}"

    def get_stats(self) -> dict:
        result = {}
        for provider, data in self.stats.items():
            avg = (data["total_latency"] / data["calls"]) if data["calls"] > 0 else 0
            result[provider] = {
                "calls": data["calls"],
                "avg_latency_ms": round(avg * 1000, 1),
                "errors": data["errors"],
                "error_rate": round(data["errors"] / data["calls"] * 100, 1) if data["calls"] > 0 else 0,
            }
        return result

    def get_recommended_model(self, task_type: str) -> tuple[str, str]:
        """Return (provider, model) for a given task type."""
        route = self.TASK_ROUTING.get(task_type, self.TASK_ROUTING["default"])
        for provider in route:
            if self.clients.get(provider) is not None:
                model = self.PROVIDER_CONFIG.get(provider, {}).get("models", [""])[0]
                return provider, model
        return "gemini", "gemini-2.5-flash"


router = ModelRouter()
