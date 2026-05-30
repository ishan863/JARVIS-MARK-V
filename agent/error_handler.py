import json
import re
import time
from pathlib import Path
from enum import Enum


class ErrorDecision(Enum):
    RETRY = "retry"
    SKIP = "skip"
    REPLAN = "replan"
    ABORT = "abort"


ERROR_ANALYST_PROMPT = """You are the error recovery module of MARK XL AI assistant.

A task step has failed. Analyze the error and decide what to do.

DECISIONS:
- retry   : Transient error (network timeout, temporary file lock, race condition).
             The same step can succeed if tried again.
- skip    : This step is not critical and the task can succeed without it.
- replan  : The approach was wrong. A different tool or method should be tried.
- abort   : The task is fundamentally impossible or unsafe to continue.

Also provide:
- A brief explanation of WHY it failed (1 sentence)
- A fix suggestion if decision is replan (what to try instead)
- Max retries: how many times to retry if decision is retry (1 or 2)

Return ONLY valid JSON:
{
  "decision": "retry|skip|replan|abort",
  "reason": "why it failed",
  "fix_suggestion": "what to try instead (for replan)",
  "max_retries": 1,
  "user_message": "Short message to tell the user (max 15 words)"
}
"""


def _use_router(prompt: str, task_type: str = "reasoning") -> str:
    try:
        from core.model_router import router
        return router.smart_route(prompt, task_type=task_type)
    except Exception:
        from core.model_router import router
        return router.generate(prompt, provider="groq")


def analyze_error(step: dict, error: str, attempt: int = 1, max_attempts: int = 2) -> dict:
    if attempt >= max_attempts:
        print(f"[ErrorHandler] ⚠️ Max attempts reached for step {step.get('step')} — forcing replan")
        return {
            "decision": ErrorDecision.REPLAN,
            "reason": f"Failed {attempt} times: {error[:100]}",
            "fix_suggestion": "Try a completely different approach or tool",
            "max_retries": 0,
            "user_message": "Trying a different approach, sir."
        }

    prompt = f"""{ERROR_ANALYST_PROMPT}

Failed step:
Tool: {step.get('tool')}
Description: {step.get('description')}
Parameters: {json.dumps(step.get('parameters', {}), indent=2)}
Critical: {step.get('critical', False)}

Error:
{error[:500]}

Attempt number: {attempt}"""

    try:
        text = _use_router(prompt, task_type="reasoning")
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        result = json.loads(text)
        decision_str = result.get("decision", "replan").lower()
        decision_map = {
            "retry": ErrorDecision.RETRY,
            "skip": ErrorDecision.SKIP,
            "replan": ErrorDecision.REPLAN,
            "abort": ErrorDecision.ABORT,
        }
        result["decision"] = decision_map.get(decision_str, ErrorDecision.REPLAN)

        if step.get("critical") and result["decision"] == ErrorDecision.SKIP:
            result["decision"] = ErrorDecision.REPLAN
            result["user_message"] = "This step is critical — finding alternative approach, sir."

        print(f"[ErrorHandler] Decision: {result['decision'].value} — {result.get('reason', '')}")
        return result

    except Exception as e:
        print(f"[ErrorHandler] ⚠️ Analysis failed: {e} — defaulting to replan")
        return {
            "decision": ErrorDecision.REPLAN,
            "reason": str(e),
            "fix_suggestion": "Try alternative approach",
            "max_retries": 1,
            "user_message": "Encountered an issue, adjusting approach, sir."
        }


def generate_fix(step: dict, error: str, fix_suggestion: str) -> dict:
    """
    When decision is REPLAN and a fix suggestion exists,
    generates a replacement step using model_router.
    """
    prompt = f"""A task step failed. Generate a replacement step.

Original step:
Tool: {step.get('tool')}
Description: {step.get('description')}
Parameters: {json.dumps(step.get('parameters', {}), indent=2)}

Error: {error[:300]}
Fix suggestion: {fix_suggestion}

Write a Python script that accomplishes the same goal differently.
Return ONLY the Python code, no explanation."""

    try:
        code = _use_router(prompt, task_type="code_gen")
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        return {
            "step": step.get("step"),
            "tool": "code_helper",
            "description": f"Auto-fix for: {step.get('description')}",
            "parameters": {
                "action": "run",
                "description": fix_suggestion,
                "code": code,
                "language": "python"
            },
            "depends_on": step.get("depends_on", []),
            "critical": step.get("critical", False)
        }

    except Exception as e:
        print(f"[ErrorHandler] ⚠️ Fix generation failed: {e}")
        return {
            "step": step.get("step"),
            "tool": "generated_code",
            "description": f"Fallback for: {step.get('description')}",
            "parameters": {"description": step.get("description", "")},
            "depends_on": step.get("depends_on", []),
            "critical": step.get("critical", False)
        }


# ---- New: Self-Healing Code Fix (Phase 4.3) ----

def auto_fix_code(error_text: str, file_path: str = None) -> str:
    """Given an error message and optional file path, try to auto-fix the code."""
    file_context = ""
    if file_path:
        p = Path(file_path)
        if p.exists():
            file_context = f"\nFile content:\n{p.read_text(encoding='utf-8', errors='replace')[:4000]}"

    prompt = f"""You are an expert debugger. Analyze this error and generate a fix.

Error:
{error_text[:1000]}
{file_context}

If the error is from MARK XL's own codebase, suggest the fix as a Python patch.
If the error is from a user-generated project, suggest the fix as corrected code.

Return ONLY valid JSON:
{{
  "fix_type": "patch|replace|manual",
  "file_path": "relative/path/to/file.py",
  "old_string": "exact string to replace (for patch)",
  "new_string": "replacement string (for patch)",
  "full_code": "complete new file content (for replace)",
  "explanation": "brief explanation of the fix"
}}"""

    try:
        text = _use_router(prompt, task_type="code_review")
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        return text
    except Exception as e:
        return json.dumps({"fix_type": "manual", "explanation": f"Auto-fix analysis failed: {e}"})


def apply_auto_patch(patch_json: str, base_dir: str = None) -> str:
    """Apply an auto-generated patch to the codebase."""
    try:
        patch = json.loads(patch_json)
    except Exception:
        return "Invalid patch format."

    root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    fix_type = patch.get("fix_type", "manual")

    if fix_type == "patch":
        fp = root / patch.get("file_path", "")
        if not fp.exists():
            return f"File not found: {fp}"
        old = patch.get("old_string", "")
        new = patch.get("new_string", "")
        if old and new:
            content = fp.read_text(encoding="utf-8")
            if old in content:
                content = content.replace(old, new)
                fp.write_text(content, encoding="utf-8")
                _log_auto_patch(patch)
                return f"Patch applied to {patch['file_path']}: {patch.get('explanation', '')}"
            return f"old_string not found in {patch['file_path']}."

    elif fix_type == "replace":
        fp = root / patch.get("file_path", "")
        full = patch.get("full_code", "")
        if full:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(full, encoding="utf-8")
            _log_auto_patch(patch)
            return f"File replaced: {patch['file_path']}: {patch.get('explanation', '')}"

    return f"Manual fix needed: {patch.get('explanation', '')}"


def _log_auto_patch(patch: dict):
    """Log auto-patches to memory for audit trail."""
    try:
        from memory.memory_manager import update_memory
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "file": patch.get("file_path", "unknown"),
            "fix_type": patch.get("fix_type", "unknown"),
            "explanation": patch.get("explanation", ""),
        }
        update_memory({"auto_patches": {entry["timestamp"]: entry}})
    except Exception:
        pass
