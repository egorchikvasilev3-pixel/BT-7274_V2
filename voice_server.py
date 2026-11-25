"""HTTP-сайдкар локального голоса БТ на Qwen3-TTS 0.6B Base.

Запуск:
    python voice_server.py --port 8765

Эндпоинты:
    GET  /health  — состояние и загруженность модели
    POST /warmup  — загрузить модель и голосовой профиль заранее
    POST /tts     — {"text": "...", "variant": "mild"} -> audio/wav
    POST /unload  — выгрузить модель из памяти
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import math
import re
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
try:
    import torch
    TORCH_AVAILABLE = True
except Exception:
    torch = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
MODEL_DIR = ROOT / "models" / "Qwen3-TTS-12Hz-0.6B-Base"
PIPER_DIR = ROOT / "models" / "piper"
PIPER_MODEL = Path(
    os.environ.get(
        "BT7274_PIPER_MODEL",
        str(PIPER_DIR / "bt7274-ru-medium.onnx" if (PIPER_DIR / "bt7274-ru-medium.onnx").exists() else PIPER_DIR / "ru_RU-ruslan-medium.onnx"),
    )
)
REF_AUDIO = ROOT / "reference" / "bt_ru_reference_7s.wav"
REF_META = ROOT / "reference" / "bt_ru_reference_7s.json"
CACHE_DIR = ROOT / "voice_cache"
LOG_PATH = ROOT / "voice_server.log"

_default_engine = "piper" if (PIPER_DIR / "bt7274-ru-medium.onnx").exists() else "qwen"
ENGINE = os.environ.get("BT7274_TTS_ENGINE", _default_engine).strip().lower()
if ENGINE not in {"piper", "qwen"}:
    ENGINE = _default_engine
MODEL_VERSION = (
    f"piper-{PIPER_MODEL.stem}-v2-slow-clear"
    if ENGINE == "piper"
    else "qwen3-tts-0.6b-base-ru-bt-v4-icl"
)
REFERENCE_VERSION = "bt-ru-ideal-v3-trim1"
MAX_TEXT = 500
DEFAULT_VARIANT = "mild"
DEFAULT_IDLE_UNLOAD_SECONDS = 900

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
LOG = logging.getLogger("bt_voice_server")


class VoiceService:
    def __init__(self, idle_unload_seconds: int = DEFAULT_IDLE_UNLOAD_SECONDS) -> None:
        self._lock = threading.RLock()
        self._model = None
        self._prompt = None
        self._piper_voice = None
        self._last_used = 0.0
        self._idle_unload_seconds = max(0, int(idle_unload_seconds))
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._idle_worker,
            name="bt-voice-idle",
            daemon=True,
        )
        self._thread.start()

    @property
    def loaded(self) -> bool:
        if ENGINE == "piper":
            return self._piper_voice is not None
        return self._model is not None

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "loaded": self.loaded,
            "engine": ENGINE,
            "device": "cuda:0" if (TORCH_AVAILABLE and torch.cuda.is_available()) and ENGINE == "qwen" else "cpu",
            "model": PIPER_MODEL.name if ENGINE == "piper" else MODEL_DIR.name,
            "version": MODEL_VERSION,
            "cuda": (TORCH_AVAILABLE and torch.cuda.is_available()),
            "vram_mb": (
                round(torch.cuda.max_memory_allocated() / (1024**2), 1)
                if (TORCH_AVAILABLE and torch.cuda.is_available())
                else 0
            ),
        }

    def _idle_worker(self) -> None:
        while not self._stop.wait(30.0):
            if self._idle_unload_seconds <= 0 or not self.loaded:
                continue
            with self._lock:
                if self.loaded and time.time() - self._last_used > self._idle_unload_seconds:
                    LOG.info("Простой, выгружаю голосовую модель для освобождения VRAM")
                    self._unload_locked()

    def warmup(self) -> dict[str, Any]:
        with self._lock:
            self._load_locked()
            self._last_used = time.time()
            return self.health()

    def unload(self) -> dict[str, Any]:
        with self._lock:
            self._unload_locked()
            return self.health()

    def _load_locked(self) -> None:
        if ENGINE == "piper":
            self._load_piper_locked()
            return
        if self._model is not None:
            return
        if not MODEL_DIR.exists():
            raise RuntimeError(f"Нет модели: {MODEL_DIR}")
        if not REF_AUDIO.exists():
            raise RuntimeError(f"Нет референса: {REF_AUDIO}")
        meta = json.loads(REF_META.read_text(encoding="utf-8"))
        ref_text = str(meta.get("transcript") or "").strip()
        x_vector_only = bool(meta.get("x_vector_only", False))

        from qwen_tts import Qwen3TTSModel

        started = time.perf_counter()
        LOG.info("Загрузка Qwen3-TTS из %s", MODEL_DIR)
        model = Qwen3TTSModel.from_pretrained(
            str(MODEL_DIR),
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
            low_cpu_mem_usage=True,
        )
        model.model.eval()
        prompt = model.create_voice_clone_prompt(
            ref_audio=str(REF_AUDIO),
            ref_text=ref_text,
            x_vector_only_mode=x_vector_only,
        )
        self._model = model
        self._prompt = prompt
        LOG.info("Reference mode: %s", "x_vector_only" if x_vector_only else "icl")
        elapsed = time.perf_counter() - started
        vram = (
            torch.cuda.max_memory_allocated() / (1024**2)
            if (TORCH_AVAILABLE and torch.cuda.is_available())
            else 0
        )
        LOG.info("Модель готова за %.2f с, VRAM %.0f МБ", elapsed, vram)

    def _load_piper_locked(self) -> None:
        if self._piper_voice is not None:
            return
        if not PIPER_MODEL.exists():
            raise RuntimeError(f"Нет Piper-модели: {PIPER_MODEL}")
        from piper import PiperVoice

        started = time.perf_counter()
        LOG.info("Загрузка Piper из %s", PIPER_MODEL)
        self._piper_voice = PiperVoice.load(PIPER_MODEL)
        LOG.info("Piper готов за %.2f с", time.perf_counter() - started)

    def _unload_locked(self) -> None:
        self._piper_voice = None
        self._model = None
        self._prompt = None
        import gc

        gc.collect()
        if (TORCH_AVAILABLE and torch.cuda.is_available()):
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        LOG.info("Голосовая модель выгружена")

    def synthesize(self, text: str, variant: str = DEFAULT_VARIANT, max_new_tokens: int | None = None) -> tuple[bytes, dict[str, Any]]:
        raw_clean = " ".join(str(text or "").split()).strip()
        if not raw_clean:
            raise ValueError("Пустой текст")
        if len(raw_clean) > MAX_TEXT:
            raw_clean = raw_clean[:MAX_TEXT].rsplit(" ", 1)[0] + "."
        if variant not in {"raw", "mild", "vanguard"}:
            variant = DEFAULT_VARIANT
        clean = prepare_tts_text(raw_clean) or raw_clean

        cache_key = hashlib.sha256(
            f"{MODEL_VERSION}|{REFERENCE_VERSION}|{variant}|{clean}".encode("utf-8")
        ).hexdigest()[:32]
        cache_path = CACHE_DIR / f"{cache_key}.wav"
        if cache_path.exists() and cache_path.stat().st_size > 2048:
            data = cache_path.read_bytes()
            return data, {"cached": True, "variant": variant, "text": clean, "engine": ENGINE}

        with self._lock:
            self._load_locked()
            self._last_used = time.time()
            started = time.perf_counter()
            if ENGINE == "piper":
                data, info = self._synthesize_piper(clean, variant)
            else:
                data, info = self._synthesize_qwen(clean, variant, max_new_tokens=max_new_tokens)
            info["synth_s"] = round(time.perf_counter() - started, 3)
            info["engine"] = ENGINE
            try:
                cache_path.write_bytes(data)
            except OSError:
                LOG.exception("Не удалось сохранить кэш")
            return data, info

    def _synthesize_piper(self, text: str, variant: str) -> tuple[bytes, dict[str, Any]]:
        from piper import SynthesisConfig

        assert self._piper_voice is not None
        # Slightly slower for calmer BT-like delivery; keep consistent.
        length_scale = 1.30 if len(text) < 120 else 1.22
        syn = SynthesisConfig(length_scale=length_scale, noise_scale=0.55, noise_w_scale=0.7)
        chunks = split_text(text, limit=220)
        pieces: list[np.ndarray] = []
        sample_rate = 22050
        for index, chunk in enumerate(chunks):
            LOG.info("Piper синтез %s/%s: %s", index + 1, len(chunks), chunk)
            raw_chunks = list(self._piper_voice.synthesize(chunk, syn_config=syn))
            if not raw_chunks:
                continue
            sample_rate = int(raw_chunks[0].sample_rate)
            audio = np.concatenate([c.audio_float_array for c in raw_chunks]).astype(np.float32)
            audio = _trim_edges(audio, sample_rate, tail_margin=0.12)
            pieces.append(audio)
            if index + 1 < len(chunks):
                pieces.append(np.zeros(int(sample_rate * 0.12), dtype=np.float32))
        if not pieces:
            raise RuntimeError("Piper не вернул аудио")
        audio = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
        audio = apply_variant(audio, sample_rate, variant)
        # Ensure there's a tiny tail so players don't clip the last phoneme.
        tail_pad = np.zeros(int(sample_rate * 0.08), dtype=np.float32)
        audio = np.concatenate([audio, tail_pad])
        buffer = io.BytesIO()
        sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
        duration = len(audio) / max(1, sample_rate)
        return buffer.getvalue(), {
            "cached": False,
            "variant": variant,
            "text": text,
            "duration_s": round(duration, 3),
            "rtf": round((time.perf_counter() - 0) / max(0.001, duration), 3),  # placeholder, overwritten
            "sample_rate": int(sample_rate),
            "vram_mb": 0,
        }

    def _synthesize_qwen(self, text: str, variant: str, max_new_tokens: int | None = None) -> tuple[bytes, dict[str, Any]]:
        assert self._model is not None
        if (TORCH_AVAILABLE and torch.cuda.is_available()):
            torch.cuda.synchronize()
        chunks = split_text(text)
        pieces: list[np.ndarray] = []
        sample_rate = 24000
        for index, chunk in enumerate(chunks):
            LOG.info("Синтез %s/%s: %s", index + 1, len(chunks), chunk)
            chunk_limit = max(192, min(1200, int(len(chunk) * 8 + 160)))
            if max_new_tokens is not None:
                try:
                    requested = int(max_new_tokens)
                except Exception:
                    requested = chunk_limit
                chunk_limit = max(128, min(1600, requested))
            wavs, sample_rate = self._model.generate_voice_clone(
                text=chunk,
                language="Russian",
                voice_clone_prompt=self._prompt,
                non_streaming_mode=True,
                max_new_tokens=chunk_limit,
                do_sample=True,
                temperature=0.68,
                top_p=0.90,
                repetition_penalty=1.05,
            )
            generated = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
            generated = _trim_edges(generated, int(sample_rate), tail_margin=0.18)
            pieces.append(generated)
            if index + 1 < len(chunks):
                pieces.append(np.zeros(int(sample_rate * 0.12), dtype=np.float32))
        audio = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
        if (TORCH_AVAILABLE and torch.cuda.is_available()):
            torch.cuda.synchronize()
        audio = apply_variant(audio, int(sample_rate), variant)
        tail_pad = np.zeros(int(sample_rate * 0.08), dtype=np.float32)
        audio = np.concatenate([audio, tail_pad])
        buffer = io.BytesIO()
        sf.write(buffer, audio, int(sample_rate), format="WAV", subtype="PCM_16")
        duration = len(audio) / max(1, int(sample_rate))
        return buffer.getvalue(), {
            "cached": False,
            "variant": variant,
            "text": text,
            "duration_s": round(duration, 3),
            "rtf": 0.0,
            "sample_rate": int(sample_rate),
            "vram_mb": (
                round(torch.cuda.max_memory_allocated() / (1024**2), 1)
                if (TORCH_AVAILABLE and torch.cuda.is_available())
                else 0
            ),
        }


    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._unload_locked()



_TTS_REPLACEMENTS = [
    (re.compile(r"\bBT[- ]?7274\b", re.IGNORECASE), "Би-Ти семь-два-семь-четыре"),
    (re.compile(r"\bБТ[- ]?7274\b", re.IGNORECASE), "Би-Ти семь-два-семь-четыре"),
    (re.compile(r"\bYouTube\b", re.IGNORECASE), "Ютуб"),
    (re.compile(r"\bSteam\b", re.IGNORECASE), "Стим"),
    (re.compile(r"\bDiscord\b", re.IGNORECASE), "Дискорд"),
    (re.compile(r"\bOBS Studio\b", re.IGNORECASE), "О-Би-Эс"),
    (re.compile(r"\bOBS\b", re.IGNORECASE), "О-Би-Эс"),
    (re.compile(r"\bOllama\b", re.IGNORECASE), "Оллама"),
    (re.compile(r"\blocalhost:11434\b", re.IGNORECASE), "локальный сервер"),
    (re.compile(r"\blocalhost\b", re.IGNORECASE), "локальный сервер"),
    (re.compile(r"\bCPU\b", re.IGNORECASE), "процессор"),
    (re.compile(r"\bGPU\b", re.IGNORECASE), "видеокарта"),
    (re.compile(r"\bRAM\b", re.IGNORECASE), "оперативная память"),
    (re.compile(r"\bVRAM\b", re.IGNORECASE), "видеопамять"),
    (re.compile(r"\bFPS\b", re.IGNORECASE), "кадров в секунду"),
    (re.compile(r"\bfps\b", re.IGNORECASE), "кадров в секунду"),
    (re.compile(r"\bAPI\b", re.IGNORECASE), "А-Пи-Ай"),
    (re.compile(r"\bHTTP\b", re.IGNORECASE), "Эйч-Ти-Ти-Пи"),
    (re.compile(r"\bTTS\b", re.IGNORECASE), "Ти-Ти-Эс"),
    (re.compile(r"\bЦП\b"), "процессор"),
    (re.compile(r"\bГП\b"), "видеокарта"),
    (re.compile(r"\bОЗУ\b"), "оперативная память"),
]

_UNITS = {0:"ноль",1:"один",2:"два",3:"три",4:"четыре",5:"пять",6:"шесть",7:"семь",8:"восемь",9:"девять",10:"десять",11:"одиннадцать",12:"двенадцать",13:"тринадцать",14:"четырнадцать",15:"пятнадцать",16:"шестнадцать",17:"семнадцать",18:"восемнадцать",19:"девятнадцать"}
_TENS = {20:"двадцать",30:"тридцать",40:"сорок",50:"пятьдесят",60:"шестьдесят",70:"семьдесят",80:"восемьдесят",90:"девяносто"}
_HUND = {100:"сто",200:"двести",300:"триста",400:"четыреста",500:"пятьсот",600:"шестьсот",700:"семьсот",800:"восемьсот",900:"девятьсот"}

def _num_words(n: int) -> str:
    if n < 0: return "минус " + _num_words(-n)
    if n < 20: return _UNITS[n]
    if n < 100:
        t, r = divmod(n, 10)
        return _TENS[t*10] if r == 0 else f"{_TENS[t*10]} {_UNITS[r]}"
    if n < 1000:
        h, r = divmod(n, 100)
        return _HUND[h*100] if r == 0 else f"{_HUND[h*100]} {_num_words(r)}"
    return str(n)

def _pct_word(n: int) -> str:
    a = abs(n) % 100
    l = a % 10
    if 11 <= a <= 14: return "процентов"
    if l == 1: return "процент"
    if l in {2,3,4}: return "процента"
    return "процентов"

def prepare_tts_text(text: str) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return ""
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[A-Za-z]:\\[^\s]+", " ", value)
    value = re.sub(r"`[^`]+`", " ", value)
    value = re.sub(r"\b[\w./\\-]+\.(?:py|exe|log|txt|json|wav|mp3|webp|png|jpg)\b", " ", value, flags=re.IGNORECASE)
    for pat, repl in _TTS_REPLACEMENTS:
        value = pat.sub(repl, value)
    value = re.sub(r"\b(\d{1,3})\s*%", lambda m: f"{_num_words(int(m.group(1)))} {_pct_word(int(m.group(1)))}", value)
    value = re.sub(r"(?<![\w/])(\d{1,3})(?![\w/])", lambda m: _num_words(int(m.group(1))) if 0 <= int(m.group(1)) <= 100 else m.group(1), value)
    value = value.replace("&", " и ").replace("/", " ")
    value = re.sub(r"[\[\]{}()<>\"'`*_#~|\\]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-—:;,.")
    return value

def split_text(text: str, limit: int = 180) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in text.replace("!", ".").replace("?", ".").split("."):
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}.".strip() if current else f"{sentence}."
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                parts.append(current)
            while len(sentence) > limit:
                cut = sentence.rfind(" ", 0, limit)
                cut = cut if cut > 40 else limit
                parts.append(sentence[:cut].strip() + ".")
                sentence = sentence[cut:].strip()
            current = sentence + "." if sentence else ""
    if current:
        parts.append(current)
    return parts or [text[:limit]]


def _trim_edges(samples: np.ndarray, sample_rate: int, tail_margin: float = 0.18) -> np.ndarray:
    """Убирает длинную тишину по краям, не обрезая финальные согласные."""
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    frame = max(128, int(sample_rate * 0.02))
    hop = max(64, int(sample_rate * 0.01))
    if data.size < frame * 2:
        return data
    pad = (-data.size) % hop
    padded = np.pad(data, (0, pad)).astype(np.float64)
    frames = np.lib.stride_tricks.sliding_window_view(padded, frame)[::hop]
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    peak = float(np.max(np.abs(data)))
    if peak <= 1e-6:
        return data
    threshold = max(peak * 10.0 ** (-42.0 / 20.0), 8e-5)
    active = np.where(rms > threshold)[0]
    if active.size == 0:
        return data
    lead_margin = int(sample_rate * 0.05)
    tail_margin_samples = int(sample_rate * max(0.12, float(tail_margin)))
    start = max(0, int(active[0]) * hop - lead_margin)
    end = min(data.size, int(active[-1]) * hop + frame + tail_margin_samples)
    if end - start < int(sample_rate * 0.08):
        return data
    return data[start:end]


def _silence_gate(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Мягкий гейт: приглушает только тихие паузы, не трогая речь."""
    if samples.size < sample_rate // 5:
        return samples
    frame = max(256, int(sample_rate * 0.02))
    hop = max(128, frame // 2)
    if samples.size < frame:
        return samples
    pad = (-samples.size) % hop
    padded = np.pad(samples, (0, pad)).astype(np.float64)
    frames = np.lib.stride_tricks.sliding_window_view(padded, frame)[::hop]
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    peak = float(np.max(rms))
    if peak < 1e-4:
        return samples
    noise_floor = float(np.percentile(rms, 15))
    speech_floor = float(np.percentile(rms, 75))
    threshold = max(noise_floor * 2.2, speech_floor * 0.05, 0.0015)
    gain = np.where(rms < threshold, 0.35, 1.0).astype(np.float64)
    # Do not gate the tail hard - final consonants are often quiet.
    tail_frames = max(1, int((sample_rate * 0.22) / hop))
    gain[-tail_frames:] = np.maximum(gain[-tail_frames:], 0.75)
    kernel = np.array([0.25, 0.5, 0.25], dtype=np.float64)
    gain = np.pad(gain, (1, 1), mode="edge")
    gain = np.convolve(gain, kernel, mode="valid")
    gain = np.clip(gain, 0.25, 1.0)
    envelope = np.interp(
        np.arange(padded.size, dtype=np.float64),
        np.arange(gain.size, dtype=np.float64) * hop,
        gain,
    )
    return ((padded * envelope)[: samples.size]).astype(np.float64)


def _peaking_eq(samples: np.ndarray, sample_rate: int, frequency: float, q: float, gain_db: float) -> np.ndarray:
    import scipy.signal as signal

    amplitude = 10.0 ** (gain_db / 40.0)
    omega = 2.0 * math.pi * frequency / sample_rate
    alpha = math.sin(omega) / (2.0 * q)
    cosine = math.cos(omega)
    b = np.array(
        [
            1.0 + alpha * amplitude,
            -2.0 * cosine,
            1.0 - alpha * amplitude,
        ]
    )
    a = np.array(
        [
            1.0 + alpha / amplitude,
            -2.0 * cosine,
            1.0 - alpha / amplitude,
        ]
    )
    b /= a[0]
    a /= a[0]
    return signal.lfilter(b, a, samples)


def _fade(samples: np.ndarray, sample_rate: int, seconds: float = 0.012) -> np.ndarray:
    count = max(1, int(sample_rate * seconds))
    if samples.size <= count * 2:
        return samples
    fade_in = np.linspace(0.0, 1.0, count, dtype=np.float32)
    samples[:count] *= fade_in
    samples[-count:] *= fade_in[::-1]
    return samples


def apply_variant(audio: np.ndarray, sample_rate: int, variant: str) -> np.ndarray:
    import scipy.signal as signal

    samples = np.nan_to_num(np.asarray(audio, dtype=np.float64).reshape(-1))
    if samples.size < 64:
        return np.clip(samples, -1.0, 1.0).astype(np.float32)

    if variant != "raw":
        sos = signal.butter(
            2,
            [65.0, min(9500.0, sample_rate * 0.45)],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )
        samples = signal.sosfilt(sos, samples)
        samples = _peaking_eq(samples, sample_rate, 150.0, 0.9, 1.2)
        samples = _peaking_eq(samples, sample_rate, 3100.0, 1.1, 1.0)
        samples = np.tanh(samples * 1.05) / math.tanh(1.05)

    if variant == "vanguard":
        samples = _flanger(samples, sample_rate)
        samples = _comb(samples, sample_rate)
        samples = _echo(samples, sample_rate)
        samples = np.tanh(samples * 1.22) / math.tanh(1.22)

    samples = _silence_gate(np.asarray(samples, dtype=np.float64), sample_rate)
    samples = _fade(samples.astype(np.float32), sample_rate)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 1e-8:
        samples = samples * (10.0 ** (-1.0 / 20.0) / peak)
    return np.clip(samples, -0.98, 0.98).astype(np.float32)


def _flanger(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    count = samples.size
    minimum_delay = max(1, int(sample_rate * 0.0011))
    maximum_delay = max(minimum_delay + 1, int(sample_rate * 0.0029))
    indices = np.arange(count, dtype=np.float64)
    modulation = 0.5 + 0.5 * np.sin(2.0 * math.pi * 0.33 * indices / sample_rate)
    delay = minimum_delay + (maximum_delay - minimum_delay) * modulation
    delay_indices = np.floor(delay).astype(np.int64)
    read_indices = np.arange(count, dtype=np.int64) - delay_indices
    valid = read_indices >= 0
    delayed = np.zeros(count, dtype=np.float64)
    delayed[valid] = samples[read_indices[valid]]
    return samples + 0.05 * delayed


def _comb(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    output = samples.copy()
    delay_a = max(1, int(sample_rate * 0.0027))
    delay_b = max(1, int(sample_rate * 0.0053))
    if samples.size > delay_a:
        output[delay_a:] += 0.10 * samples[:-delay_a]
    if samples.size > delay_b:
        output[delay_b:] -= 0.05 * samples[:-delay_b]
    return output


def _echo(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    output = samples.copy()
    delay_one = max(1, int(sample_rate * 0.043))
    delay_two = max(1, int(sample_rate * 0.087))
    if samples.size > delay_one:
        output[delay_one:] += 0.09 * samples[:-delay_one]
    if samples.size > delay_two:
        output[delay_two:] += 0.04 * samples[:-delay_two]
    return output


SERVICE: VoiceService | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "BTVoiceServer/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.client_address[0], fmt % args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64 * 1024:
            raise ValueError("Некорректная длина запроса")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Ожидался JSON-объект")
        return data

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/health":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        assert SERVICE is not None
        self._send_json(HTTPStatus.OK, SERVICE.health())

    def do_POST(self) -> None:
        assert SERVICE is not None
        route = self.path.split("?", 1)[0]
        try:
            if route == "/warmup":
                self._send_json(HTTPStatus.OK, SERVICE.warmup())
                return
            if route == "/unload":
                self._send_json(HTTPStatus.OK, SERVICE.unload())
                return
            if route != "/tts":
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                return
            payload = self._read_json()
            text = str(payload.get("text") or "")
            variant = str(payload.get("variant") or DEFAULT_VARIANT)
            max_new_tokens = payload.get("max_new_tokens")
            data, info = SERVICE.synthesize(text, variant, max_new_tokens=max_new_tokens)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-BT-Voice-Cached", "1" if info.get("cached") else "0")
            self.send_header("X-BT-Voice-Meta", json.dumps(info, ensure_ascii=True))
            self.end_headers()
            self.wfile.write(data)
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
        except Exception as error:
            LOG.exception("Ошибка синтеза")
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": f"{type(error).__name__}: {error}"},
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--preload", action="store_true")
    parser.add_argument("--idle-unload", type=int, default=DEFAULT_IDLE_UNLOAD_SECONDS)
    args = parser.parse_args()

    global SERVICE
    SERVICE = VoiceService(idle_unload_seconds=args.idle_unload)
    if args.preload:
        SERVICE.warmup()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    LOG.info("Сервер голоса слушает http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Остановка по Ctrl+C")
    finally:
        server.server_close()
        SERVICE.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
