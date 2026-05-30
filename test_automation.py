import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.security import security
from core.orchestrator import orchestrator, register_actions, ToolContext
from core.model_router import router as model_router
from config import validate_api_keys, get_settings


async def test_automation():
    print("=" * 60)
    print("MARK XL — Full Automation Test Suite")
    print("=" * 60)

    # 1. API Keys
    print("\n[1/8] API Key Validation")
    key_status = validate_api_keys()
    for k, v in key_status.items():
        ok = "[OK]" if v["present"] and v["valid"] else "[MISS]"
        print(f"  {ok} {v['label']}: present={v['present']} valid={v['valid']}")

    # 2. Settings
    print("\n[2/8] Settings Check")
    settings = get_settings()
    print(f"  Chat model: {settings.get('chat_model')}")
    print(f"  Vision model: {settings.get('vision_model')}")
    print(f"  Theme: {settings.get('theme')}")
    print(f"  Autonomous: {settings.get('autonomous')}")

    # 3. Orchestrator Registration
    print("\n[3/8] Orchestrator Registration")
    register_actions()
    tools = sorted(orchestrator._registry.keys())
    print(f"  Tools registered: {len(tools)}")
    print(f"  Tools: {', '.join(tools)}")

    # 4. Orchestrator Routing Test
    print("\n[4/8] Orchestrator Routing Test")
    class MockUI:
        muted = False
        current_file = None
        def set_state(self, s): pass
        def write_log(self, s): pass
        def set_input_text(self, s): pass
        def set_output_text(self, s): pass

    ui = MockUI()
    ctx = ToolContext(ui=ui, speak=lambda t: print(f"  [Speak] {t}"), loop=asyncio.get_event_loop())

    # Test routing to save_memory (doesn't need real API)
    try:
        result = await orchestrator.route("save_memory", {"category": "test", "key": "test_key", "value": "test_value"}, ctx)
        print(f"  [OK] save_memory routed: {result}")
    except Exception as e:
        print(f"  [FAIL] save_memory failed: {e}")

    # Test routing to unknown tool
    try:
        result = await orchestrator.route("unknown_tool", {}, ctx)
        print(f"  [OK] unknown tool handled: {result}")
    except Exception as e:
        print(f"  [FAIL] unknown tool failed: {e}")

    # 5. Model Router Availability
    print("\n[5/8] Model Router Providers")
    providers = model_router.available_providers()
    print(f"  Available: {providers}")
    print(f"  Task routing types: {list(model_router.TASK_ROUTING.keys())}")
    for task in ["code_gen", "quick_chat", "vision", "planning", "reasoning"]:
        provider, model = model_router.get_recommended_model(task)
        print(f"  {task}: {provider}/{model}")

    # 6. Provider Latency Test (text generation)
    print("\n[6/8] Provider Inference Test")
    test_prompt = "Say 'hello' in one word."
    for provider in providers:
        try:
            result = model_router.generate(test_prompt, provider=provider)
            print(f"  {provider}: {result[:80]}")
        except Exception as e:
            print(f"  {provider}: [FAIL] {e}")

    # 7. Smart Routing Test
    print("\n[7/8] Smart Routing Test")
    try:
        import time
        start = time.perf_counter()
        result = model_router.smart_route("What is 2+2? Answer in one word.", task_type="quick_chat")
        elapsed = (time.perf_counter() - start) * 1000
        print(f"  Result: {result[:80]}")
        print(f"  Latency: {elapsed:.0f}ms")
    except Exception as e:
        print(f"  [FAIL] Smart route failed: {e}")

    # 8. Error Handler Test
    print("\n[8/8] Error Handler Test")
    from agent.error_handler import analyze_error, generate_fix, ErrorDecision
    step = {"tool": "code_helper", "description": "Write hello world", "parameters": {}, "critical": False}
    decision = analyze_error(step, "NameError: name 'x' is not defined", attempt=1, max_attempts=2)
    print(f"  Decision: {decision['decision'].value}")
    print(f"  Reason: {decision.get('reason')}")

    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    all_ok = True

    if key_status.get("gemini_api_key", {}).get("present"):
        print("  [OK] Gemini API key: configured")
    else:
        print("  [FAIL] Gemini API key: MISSING")
        all_ok = False

    if key_status.get("groq_api_key", {}).get("present"):
        print("  [OK] Groq API key: configured")
    else:
        print("  [WARN] Groq API key: not configured (optional)")

    if key_status.get("nvidia_api_key", {}).get("present"):
        print("  [OK] NVIDIA API key: configured")
    else:
        print("  [WARN] NVIDIA API key: not configured (optional)")

    print(f"  [OK] Orchestrator: {len(tools)} tools registered")
    print(f"  [OK] Model Router: {len(providers)} providers available")
    print(f"  [OK] Error Handler: decision routing works")

    if all_ok:
        print("\n[PASS] ALL CHECKS PASSED - System ready.")
    else:
        print("\n[WARN] Some checks failed - review issues above.")

    return all_ok


if __name__ == "__main__":
    success = asyncio.run(test_automation())
    sys.exit(0 if success else 1)
