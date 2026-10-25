"""Offline text-to-speech voice guidance engine for PathAble (Proposal Section 7.4, 8, 14).

Designed for low latency (budget <= 300 ms) and reliable offline operation.
Supports real TTS (via pyttsx3 or Windows SAPI) with automatic graceful fallback
to mock/simulated audio when running in headless environments, tests, or systems
without audio output devices.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Literal

logger = logging.getLogger("pathable.voice")


@dataclass(frozen=True)
class SpeechRecord:
    timestamp: float
    text: str
    latency_ms: float
    mode: str
    latency_scope: str = "queue_dispatch"
    audible_start_latency_ms: float | None = None


class VoiceGuidance:
    """Non-blocking, debounced speech synthesizer for local navigation warnings."""

    def __init__(
        self,
        mode: Literal["auto", "tts", "mock"] = "auto",
        speech_rate: int = 160,
        cooldown_s: float = 2.0,
    ):
        self.cooldown_s = cooldown_s
        self.speech_rate = speech_rate
        self.requested_mode = mode
        self.active_mode = "mock"
        self._last_spoken_text: str | None = None
        self._last_spoken_time: float = 0.0
        self.history: list[SpeechRecord] = []
        self._lock = threading.Lock()

        self._tts_engine = None
        self._sapi_speaker = None
        self._powershell = None

        if mode in ("auto", "tts"):
            self._init_tts_engine()

        # Speech worker thread for non-blocking utterance processing
        self._queue: queue.Queue[tuple[str, float] | None] = queue.Queue()
        self._worker_thread = threading.Thread(
            target=self._speech_worker, name="PathAble-VoiceWorker", daemon=True
        )
        self._worker_thread.start()

    def _init_tts_engine(self) -> None:
        """Attempts to initialize pyttsx3 or native Windows SAPI."""
        # 1. Try pyttsx3
        try:
            import pyttsx3  # type: ignore

            engine = pyttsx3.init()
            engine.setProperty("rate", self.speech_rate)
            self._tts_engine = engine
            self.active_mode = "pyttsx3"
            logger.info("Voice initialized using pyttsx3")
            return
        except Exception as e:
            logger.debug("pyttsx3 initialization failed (%s); trying win32com SAPI", e)

        # 2. Try native SAPI via win32com
        try:
            import win32com.client  # type: ignore

            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            # Test if audio rendering works
            speaker.Rate = int((self.speech_rate - 150) / 25)
            self._sapi_speaker = speaker
            self.active_mode = "sapi"
            logger.info("Voice initialized using native SAPI.SpVoice")
            return
        except Exception as e:
            logger.debug("SAPI initialization failed (%s); falling back to mock mode", e)

        # Windows includes System.Speech even when optional Python packages are absent.
        # Start it in the worker's own process, avoiding cross-thread COM objects.
        if sys.platform == "win32":
            executable = shutil.which("powershell.exe")
            if executable:
                try:
                    subprocess.run(
                        [executable, "-NoProfile", "-NonInteractive", "-Command",
                         "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech; "
                         "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Dispose()"],
                        check=True, capture_output=True, timeout=15,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    self._powershell = executable
                    self.active_mode = "windows_speech"
                    return
                except (OSError, subprocess.SubprocessError) as exc:
                    logger.debug("Built-in Windows speech unavailable: %s", exc)

        self.active_mode = "mock"
        logger.info("Voice running in mock/simulated mode (no active audio device)")

    def _speech_worker(self) -> None:
        """Background thread executing speech so local navigation loop is never blocked."""
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            text, queued_at = item
            try:
                if self.active_mode == "pyttsx3" and self._tts_engine:
                    self._tts_engine.say(text)
                    self._tts_engine.runAndWait()
                elif self.active_mode == "sapi" and self._sapi_speaker:
                    # 0 = synchronous within the background worker thread
                    self._sapi_speaker.Speak(text, 0)
                elif self.active_mode == "windows_speech" and self._powershell:
                    # Text goes through stdin, never into executable PowerShell code.
                    command = (
                        "$ErrorActionPreference='Stop'; "
                        "[Console]::InputEncoding=[System.Text.Encoding]::UTF8; "
                        "Add-Type -AssemblyName System.Speech; "
                        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        "try { $s.SetOutputToDefaultAudioDevice(); "
                        "$s.Speak([Console]::In.ReadToEnd()) } finally { $s.Dispose() }"
                    )
                    subprocess.run(
                        [self._powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                        input=text, encoding="utf-8", check=True, capture_output=True,
                        timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    # Mock mode: sleep briefly to simulate natural speech start
                    time.sleep(0.01)
            except Exception as e:
                logger.warning("TTS playback error (%s); falling back to mock", e)
                self.active_mode = "mock"
            finally:
                self._queue.task_done()

    def speak(
        self,
        text: str,
        force: bool = False,
        priority: bool = False,
        now: float | None = None,
    ) -> float:
        """Issues a speech warning.

        Args:
            text: Utterance to speak.
            force: If True, bypasses cooldown debouncing (e.g. for urgent reroute or stop).
            priority: If True, clears any queued pending utterances.
            now: Current timestamp (defaults to time.time()).

        Returns:
            Dispatch latency in milliseconds.
        """
        if not text or not text.strip():
            return 0.0

        t0 = time.perf_counter()
        current_time = time.time() if now is None else now

        with self._lock:
            # Deduplicate identical message within cooldown period unless forced
            if not force and text == self._last_spoken_text:
                if current_time - self._last_spoken_time < self.cooldown_s:
                    return 0.0

            if priority:
                # Discard pending items in queue
                while not self._queue.empty():
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except queue.Empty:
                        break

            self._last_spoken_text = text
            self._last_spoken_time = current_time
            self._queue.put((text, current_time))

            latency_ms = (time.perf_counter() - t0) * 1000.0
            record = SpeechRecord(
                timestamp=current_time,
                text=text,
                latency_ms=latency_ms,
                mode=self.active_mode,
            )
            self.history.append(record)
            return latency_ms

    def get_last_spoken(self) -> str | None:
        """Returns the most recent spoken text."""
        with self._lock:
            return self._last_spoken_text

    def get_history(self) -> list[SpeechRecord]:
        """Returns a snapshot copy of all spoken records."""
        with self._lock:
            return list(self.history)

    def clear_history(self) -> None:
        """Clears speech history."""
        with self._lock:
            self.history.clear()
            self._last_spoken_text = None
            self._last_spoken_time = 0.0

    def wait_until_done(self, timeout: float = 3.0) -> None:
        """Blocks until the queue is drained, useful for tests or demo finish."""
        self._queue.join()

    def close(self) -> None:
        """Stops the speech worker thread cleanly."""
        self._queue.put(None)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
