## Goal
- Fix persistent Gemini 1007 crash and make phone voice chat + file transfer work reliably.

## Constraints & Preferences
- Phone mic: raw PCM16 (no ffmpeg) via Web Audio API
- Text input via `send_realtime_input(text=...)` + `send_client_content(turn_complete=True)` — avoids SDK interleaving warnings
- Google-genai SDK v2.7.0 (upgraded from 1.65.0)
- Model: `gemini-3.1-flash-live-preview` (switched from deprecated `models/gemini-2.5-flash-native-audio-preview-12-2025`)
- API version: SDK default (no explicit version set)
- SSL cert for iOS mic (HTTPS), Three.js glassmorphism UI, chromadb telemetry silenced

## Current State
### Done
- **Runtime errors fixed**: FastAPI `on_startup`→`lifespan`, starlette pinned, ARRAY items sub-schema, chromadb telemetry
- **Mic, streaming, file nav, phone file push** all implemented
- **Audio data validation**: `_convert_to_pcm16()` returns `b""` on decode failure
- **`session_resumption` removed** from config
- **`realtime_input_config` removed**: deprecated model didn't need it
- **`speech_config` kept**: needed by TTS-based `gemini-3.1-flash-live-preview`
- **`audio=` param** in `_send_realtime()`: official Google docs use `audio=`, not `media=`
- **Model switched** to `gemini-3.1-flash-live-preview` (current recommended model)
- **SDK upgraded** from 1.65.0 → 2.7.0
- **API version**: removed explicit `v1beta`/`v1alpha`, using SDK default
- **Removed `_signal_turn_complete` + dead code**: the local-VAD-driven `send_client_content(turn_complete=True)` was never executed (behind unreachable `return`), and was causing interleaving confusion
- **Text sending → `send_realtime_input(text=...)`**: in `main.py`, `core/remote_manager.py`, `core/assistant.py`

### In Progress
- **1007 crash** on deprecated model `gemini-2.5-flash-native-audio-preview-12-2025` — confirmed deprecated, migrating to `gemini-3.1-flash-live-preview`

### Next Steps
1. Test with `gemini-3.1-flash-live-preview` (current recommended model)

## Critical Context
- **Original model deprecated**: `gemini-2.5-flash-native-audio-preview-12-2025` is marked deprecated and will be shut down. This explains the persistent 1007 crash — the server rejects the deprecated model's audio format.
- **Recommended model**: `gemini-3.1-flash-live-preview` — optimized for low-latency, real-time dialogue with native audio output
- **1007**: server-side close with "Request contains an invalid argument" — caused by using deprecated model
- **1008**: model not found for API version — avoided by using SDK default API version

## Key Files
- `main.py`: `_build_config()` (line 877), `_send_realtime()` (line 953), `_receive_audio()` (line 1145)
- `server/remote_server.py:540-594`: `_convert_to_pcm16()`
- `server/static/app.js:353-459`: Web Audio API PCM16 recording
- `core/remote_manager.py:195-206`, `core/assistant.py:112-145`: text sending pattern
