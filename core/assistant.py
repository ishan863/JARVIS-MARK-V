import asyncio
import json
import re
import threading
import time
import traceback
from pathlib import Path
import sys

import sounddevice as sd
try:
    import google.genai as genai
    from google.genai import types
except ImportError:
    pass

from memory.memory_manager import load_memory, format_memory_for_prompt

from core.orchestrator import orchestrator, register_actions, ToolContext

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

from core.security import security

def _get_api_key() -> str:
    try:
        keys = security.decrypt_keys()
        key = keys.get("gemini_api_key", "").strip()
        if not (key.startswith("AIzaSy") or key.startswith("AQ.")):
            return ""
        return key
    except:
        return ""

def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

# Import the tool declarations from main.py
from main import TOOL_DECLARATIONS

class HeadlessUI:
    def __init__(self, manager):
        self.manager = manager
        self.muted = False
        self.current_file = None
        self.on_text_command = None

    def set_state(self, state: str):
        asyncio.run_coroutine_threadsafe(
            self.manager.broadcast({"type": "state", "data": state}),
            asyncio.get_event_loop()
        )

    def write_log(self, text: str):
        asyncio.run_coroutine_threadsafe(
            self.manager.broadcast({"type": "log", "data": text}),
            asyncio.get_event_loop()
        )

    def set_input_text(self, text: str):
        asyncio.run_coroutine_threadsafe(
            self.manager.broadcast({"type": "input", "data": text}),
            asyncio.get_event_loop()
        )

    def set_output_text(self, text: str):
        asyncio.run_coroutine_threadsafe(
            self.manager.broadcast({"type": "output", "data": text}),
            asyncio.get_event_loop()
        )

class AssistantLive:
    def __init__(self, ui: HeadlessUI):
        self.ui = ui
        self.session = None
        self.audio_in_queue = None
        self.out_queue = None
        self._loop = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self._last_speak_end_time = 0.0
        self.ui.on_text_command = self._on_text_command
        self._turn_done_event = None
        self._speaking_start_time = 0.0

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
            if value:
                self._speaking_start_time = time.time()
            if not value:
                self._last_speak_end_time = time.time()
                self._speaking_start_time = 0.0
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime
        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = f"[CURRENT DATE & TIME]\nRight now it is: {time_str}\nUse this to calculate exact times for reminders.\n\n"
        lang_ctx = (
            "[LANGUAGE CONFIG]\n"
            "The user speaks Hindi and English (Hinglish). "
            "Understand both Hindi (hi) and English (en) speech. "
            "Respond in the same language the user speaks.\n\n"
        )
        parts = [time_ctx, lang_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=250,
                    prefix_padding_ms=150,
                ),
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ALL_INPUT,
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        print(f"[JARVIS] [Tool] {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "file_processor":
            if not args.get("file_path") and self.ui.current_file:
                args["file_path"] = self.ui.current_file

        context = ToolContext(ui=self.ui, speak=self.speak, loop=asyncio.get_event_loop())

        try:
            result = await orchestrator.route(name, args, context)
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        is_silent = isinstance(result, dict) and result.get("silent")
        if isinstance(result, dict) and "result" in result:
            result = result["result"]

        if not self.ui.muted and not is_silent:
            self.ui.set_state("LISTENING")
        print(f"[JARVIS] [Result] {name} -> {str(result)[:80]}")
        return types.FunctionResponse(id=fc.id, name=name, response={"result": result})

    async def _send_realtime(self):
        print("[JARVIS] [Send] Started")
        while True:
            try:
                msg = await self.out_queue.get()
                await self.session.send_realtime_input(
                    audio=types.Blob(
                        data=msg["data"],
                        mime_type=msg.get("mime_type", "audio/pcm;rate=16000")
                    )
                )
            except Exception as e:
                print(f"[JARVIS] [Error] Send realtime: {e}")

    async def _listen_audio(self):
        import numpy as np
        loop = asyncio.get_event_loop()
        chunk_count = 0
        sent_count = 0
        last_report_time = time.time()
        device_idx = None
        base_boost = 1.5
        agc_gain = base_boost
        try:
            config_data = security.decrypt_keys()
            if "mic_device_index" in config_data:
                device_idx = int(config_data["mic_device_index"])
            if "mic_boost" in config_data:
                base_boost = float(config_data["mic_boost"])
                agc_gain = base_boost
        except Exception:
            pass

        try:
            device_info = sd.query_devices(device_idx, kind='input') if device_idx is not None else sd.query_devices(kind='input')
            native_sr = int(device_info['default_samplerate'])
        except Exception:
            native_sr = SEND_SAMPLE_RATE

        def callback(indata, frames, time_info, status):
            nonlocal chunk_count, sent_count, last_report_time, agc_gain
            if status:
                print(f"[MIC] Audio callback status: {status}")

            with self._speaking_lock:
                jarvis_speaking = self._is_speaking

            if not jarvis_speaking and not self.ui.muted:
                if native_sr != SEND_SAMPLE_RATE:
                    num_samples = int(frames * SEND_SAMPLE_RATE / native_sr)
                    xp = np.arange(frames)
                    x = np.linspace(0, frames - 1, num_samples)
                    resampled = np.interp(x, xp, indata.flatten())
                    out_data = resampled
                else:
                    out_data = indata.flatten().astype(np.float32)

                rms = np.sqrt(np.mean(out_data**2))
                if rms > 50:
                    target_rms = 4000.0
                    instant_gain = target_rms / rms
                    instant_gain = np.clip(instant_gain, 1.0, 8.0)
                    agc_gain = 0.8 * agc_gain + 0.2 * instant_gain
                else:
                    agc_gain = 0.95 * agc_gain + 0.05 * base_boost
                out_data = out_data * agc_gain

                out_data_int = np.clip(out_data, -32768, 32767).astype(np.int16)
                data = out_data_int.tobytes()
                amplitude = int(np.max(np.abs(out_data_int)))

                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}", "amplitude": amplitude}
                )
                sent_count += 1

                now = time.time()
                if now - last_report_time > 5:
                    flow_rate = sent_count / (now - last_report_time)
                    print(f"[MIC] ✓ Audio flow: {flow_rate:.1f} chunks/sec ({sent_count} sent)")
                    sent_count = 0
                    last_report_time = now
            else:
                if chunk_count % 100 == 0:
                    reason = []
                    if jarvis_speaking:
                        reason.append("JARVIS_SPEAKING")
                    if self.ui.muted:
                        reason.append("UI_MUTED")
                    print(f"[MIC] ✗ Audio blocked: {','.join(reason)}")
            chunk_count += 1

        try:
            with sd.InputStream(
                device=device_idx,
                samplerate=native_sr,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE if native_sr == SEND_SAMPLE_RATE else int(CHUNK_SIZE * native_sr / SEND_SAMPLE_RATE),
                callback=callback,
            ):
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] [Error] Mic: {e}")

    async def _receive_audio(self):
        out_buf, in_buf = [], []
        try:
            while True:
                async for response in self.session.receive():
                    if response.data:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content
                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)
                                current_output = " ".join(out_buf).strip()
                                self.ui.set_output_text(current_output)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)
                                current_transcript = " ".join(in_buf).strip()
                                self.ui.set_input_text(current_transcript)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []
                            self.ui.set_input_text("")

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                            out_buf = []
                            self.ui.set_output_text("")

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(function_responses=fn_responses)
        except Exception as e:
            print(f"[JARVIS] [Error] Recv: {e}")
            traceback.print_exc()

    async def _play_audio(self):
        import numpy as np
        speaker_idx = None
        output_volume = 2.0
        try:
            config_data = security.decrypt_keys()
            if "speaker_device_index" in config_data:
                speaker_idx = int(config_data["speaker_device_index"])
            if "output_volume" in config_data:
                output_volume = float(config_data["output_volume"])
        except Exception:
            pass

        stream = sd.RawOutputStream(
            device=speaker_idx,
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        MAX_SPEAKING_DURATION = 20.0
        try:
            empty_time = 0.0
            while True:
                try:
                    chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
                    empty_time = 0.0
                except asyncio.TimeoutError:
                    empty_time += 0.1
                    if self.audio_in_queue.empty():
                        if (self._turn_done_event and self._turn_done_event.is_set()) or empty_time > 1.5 or (self._speaking_start_time > 0 and time.time() - self._speaking_start_time > MAX_SPEAKING_DURATION):
                            self.set_speaking(False)
                            if self._turn_done_event:
                                self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                audio_np *= output_volume
                chunk = np.clip(audio_np, -32768, 32767).astype(np.int16).tobytes()
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] [Error] Play: {e}")
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        api_key = _get_api_key()
        if not api_key:
            self.ui.write_log("SYS: Gemini API Key missing. Please provide API Keys.")
            return

        client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session
                    self._loop = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue()
                    self._turn_done_event = asyncio.Event()
                    self.ui.muted = False

                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                traceback.print_exc()
            self.set_speaking(False)
            self.ui.set_state("THINKING")
            await asyncio.sleep(3)

