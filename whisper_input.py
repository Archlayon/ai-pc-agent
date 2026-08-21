"""
Voice input via faster-whisper (offline speech-to-text).

Records from the default microphone, transcribes, and returns text.
"""
import io
import queue
import threading

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
CHANNELS = 1


def _record_until_silence(silence_threshold: float = 0.02, silence_seconds: float = 1.5, max_seconds: float = 30):
    q = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            pass
        q.put(indata.copy())

    recorded = []
    silence_start = None
    start_time = threading.Event()
    start_time.set()

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32", callback=callback):
        while True:
            chunk = q.get()
            recorded.append(chunk)
            rms = np.sqrt(np.mean(chunk**2))
            if rms < silence_threshold:
                if silence_start is None:
                    silence_start = threading.Event()
                    silence_start.set()
                # We'll check duration outside
            else:
                silence_start = None

            # Check total length
            total_samples = sum(c.shape[0] for c in recorded)
            total_seconds = total_samples / SAMPLE_RATE
            if total_seconds >= max_seconds:
                break
            if silence_start and total_seconds > silence_seconds:
                break

    audio = np.concatenate(recorded, axis=0).flatten()
    return audio


def listen(model_size: str = "small") -> str:
    model = WhisperModel(model_size, compute_type="int8")
    audio = _record_until_silence()
    segments, _ = model.transcribe(audio, beam_size=5)
    text = "".join(segment.text for segment in segments).strip()
    return text
