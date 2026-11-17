#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BT-7274 local voice agent with a transparent PySide6 holographic overlay."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import importlib
import importlib.util
import logging
import logging.handlers
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "logs" / "bt7274.log"
HELMET_PATH = BASE_DIR / "helmet.webp"
TTS_CACHE_DIR = BASE_DIR / "bt_voice_cache"
SHOTS_DIR = BASE_DIR / "shots"
CLIPS_DIR = BASE_DIR / "clips"
DATA_DIR = BASE_DIR / "data"
NOTES_PATH = DATA_DIR / "notes.txt"
CHAT_HISTORY_PATH = BASE_DIR / "chat_history.txt"
SHUTDOWN_REQUEST_PATH = DATA_DIR / "shutdown.request"
CHAT_HISTORY_HEADER = "# Журнал синхронизации БТ-7274\n"
CHAT_HISTORY_MAX_BYTES = 512 * 1024
CHAT_HISTORY_KEEP_LINES = 400

APP_NAME = "BT-7274"
APP_VERSION = "1.0.0"
OVERLAY_WIDTH = 380
OVERLAY_HEIGHT = 370
OVERLAY_CARD_WIDTH = 320
OVERLAY_CARD_HEIGHT = 180
OVERLAY_MARGIN_RIGHT = 15
OVERLAY_MARGIN_TOP = 60
try:
    _overlay_fps = int(os.environ.get("BT7274_OVERLAY_FPS", "60") or 60)
except ValueError:
    _overlay_fps = 60
OVERLAY_FPS = max(30, min(60, _overlay_fps))
OVERLAY_FRAME_MS = max(16, int(round(1000 / OVERLAY_FPS)))

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_PS_URL = "http://localhost:11434/api/ps"
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_KEEP_ALIVE = os.environ.get("BT7274_OLLAMA_KEEP_ALIVE", "5m")

WHISPER_GPU_MODEL = "small"
WHISPER_CPU_MODEL = "base"
WHISPER_GPU_COMPUTE_TYPE = "float16"
WHISPER_CPU_COMPUTE_TYPE = "int8"

TTS_VOICE = "ru-RU-DmitryNeural"
TTS_RATE = "-6%"
TTS_PITCH = "-12Hz"
TTS_PROXY_ENV = "BT7274_TTS_PROXY"
TTS_ATTEMPTS = 3
TTS_RETRY_DELAY = 0.4
TTS_CONNECT_TIMEOUT = 10
TTS_RECEIVE_TIMEOUT = 60
TTS_UNAVAILABLE_COOLDOWN = 60.0
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_LAUNCH_TIMEOUT = 20.0
VOICE_FILTER_VERSION = "vanguard-v4"
WARMUP_ENABLED = os.environ.get("BT7274_WARMUP", "1").strip().lower() not in {
    "0",
    "false",
    "off",
    "no",
}
INSTANCE_LOCK_PATH = BASE_DIR / ".bt7274.lock"

AUDIO_SAMPLE_RATE = 16000
MIC_BLOCKSIZE = 1024
MAX_RECORD_SECONDS = 45
SCREENSHOT_PREFIX = "bt_screenshot"
VIDEO_PREFIX = "bt_highlight"
SCREENSHOT_PREFIXES = (SCREENSHOT_PREFIX, "screenshot_")
VIDEO_PREFIXES = (VIDEO_PREFIX, "clip_")
RECORD_TAGS = ("RECORD_VIDEO_START", "RECORD_VIDEO_STOP")

ACTION_TAGS = (
    "OPEN_YOUTUBE",
    "OPEN_MUSIC",
    "TAKE_SCREENSHOT",
    "RECORD_VIDEO_START",
    "RECORD_VIDEO_STOP",
    "MEDIA_PLAY_PAUSE",
    "MEDIA_NEXT",
    "MEDIA_PREV",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "OPEN_EXPLORER",
    "EMPTY_TRASH",
    "OPEN_NOTEPAD",
    "OPEN_CALC",
    "OPEN_STEAM",
    "OPEN_DISCORD",
    "OPEN_BROWSER",
    "WINDOW_MINIMIZE_ALL",
    "WINDOW_CLOSE",
    "WINDOW_SWITCH",
    "LOCK_PC",
    "OBS_PAUSE",
    "OBS_RESUME",
    "OBS_NEXT_SCENE",
)
DEFAULT_ACTION_RESPONSES = {
    "OPEN_YOUTUBE": "Видеоканал YouTube открыт, пилот.",
    "OPEN_MUSIC": "Музыкальный канал открыт, пилот.",
    "TAKE_SCREENSHOT": "Снимок сектора выполнен, пилот.",
    "RECORD_VIDEO_START": "Запись экрана запущена, пилот. Ожидаю команду стоп.",
    "RECORD_VIDEO_STOP": "Запись успешно завершена и сохранена в архив, Пилот.",
    "MEDIA_PLAY_PAUSE": "Воспроизведение переключено, пилот.",
    "MEDIA_NEXT": "Следующий трек, пилот.",
    "MEDIA_PREV": "Предыдущий трек, пилот.",
    "VOLUME_UP": "Громкость повышена, пилот.",
    "VOLUME_DOWN": "Громкость понижена, пилот.",
    "OPEN_EXPLORER": "Проводник открыт, пилот.",
    "EMPTY_TRASH": "Корзина очищена, пилот.",
    "OPEN_NOTEPAD": "Блокнот открыт, пилот.",
    "OPEN_CALC": "Калькулятор открыт, пилот.",
    "OPEN_STEAM": "Steam запущен, пилот.",
    "OPEN_DISCORD": "Discord запущен, пилот.",
    "OPEN_BROWSER": "Браузер открыт, пилот.",
    "WINDOW_MINIMIZE_ALL": "Все окна свёрнуты, пилот.",
    "WINDOW_CLOSE": "Активное окно закрыто, пилот.",
    "WINDOW_SWITCH": "Переключаю окно, пилот.",
    "LOCK_PC": "Блокировка выполнена, пилот.",
    "OBS_PAUSE": "Запись приостановлена, пилот.",
    "OBS_RESUME": "Запись продолжена, пилот.",
    "OBS_NEXT_SCENE": "Сцена переключена, пилот.",
    "NO_ACTION": "Приказ принят, пилот.",
}
KNOWN_TAGS = set(ACTION_TAGS) | {"NO_ACTION"}
TAG_ALT = "|".join(re.escape(tag) for tag in sorted(KNOWN_TAGS))
KNOWN_TAG_RE = re.compile(r"\[(" + TAG_ALT + r")\]", re.IGNORECASE)
LEADING_TAG_RE = re.compile(r"^\s*\[([A-Za-z][A-Za-z0-9_]*)\]\s*")
WAKE_PREFIX_RE = re.compile(
    r"^[\s\-–—]*(?:(?:б\s*т|бэ\s*тэ|би[\s-]*ти|bt)(?:\s*[-–—]?\s*7274)?)"
    r"(?=$|[\s,.:;!?…—–-])[\s,.:;!?…—–-]*",
    re.IGNORECASE,
)
TAG_ALIASES = {
    "MEDIA_PLAYPAUSE": "MEDIA_PLAY_PAUSE",
    "MEDIA_PLAY": "MEDIA_PLAY_PAUSE",
    "PLAY_PAUSE": "MEDIA_PLAY_PAUSE",
    "NEXT_TRACK": "MEDIA_NEXT",
    "PREV_TRACK": "MEDIA_PREV",
    "PREVIOUS_TRACK": "MEDIA_PREV",
    "YOUTUBE": "OPEN_YOUTUBE",
    "MUSIC": "OPEN_MUSIC",
    "SCREENSHOT": "TAKE_SCREENSHOT",
    "RECORD": "RECORD_VIDEO_START",
    "RECORD_VIDEO": "RECORD_VIDEO_START",
    "START_RECORD": "RECORD_VIDEO_START",
    "STOP_RECORD": "RECORD_VIDEO_STOP",
    "EXPLORER": "OPEN_EXPLORER",
    "TRASH": "EMPTY_TRASH",
}
NEGATION_RE = re.compile(
    r"\bне\s+(?:надо|нужно)\b|"
    r"\bне\s+(?:открывай|открой|включай|включи|ставь|поставь|делай|сделай|"
    r"очищай|очисти|записывай|запиши|переключай|переключи|прибавляй|прибавь|"
    r"убавляй|убавь)\b",
    re.IGNORECASE,
)
TRANSLITERATION_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bcorzina\b", re.IGNORECASE), "Корзина"),
    (re.compile(r"\bprovodnik\b", re.IGNORECASE), "Проводник"),
    (re.compile(r"\bgromkost\b", re.IGNORECASE), "Громкость"),
)
ACTION_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:пауза|приостанови|поставь\s+на\s+паузу)\b.*\b(?:запис\w*|видео|съемк\w*|съёмк\w*)\b|"
            r"\b(?:запис\w*|видео|съемк\w*|съёмк\w*)\b.*\bпаузу\b",
            re.IGNORECASE,
        ),
        "OBS_PAUSE",
    ),
    (
        re.compile(
            r"\b(?:продолжи|возобнови|сними\s+с\s+паузы)\b.*\b(?:запис\w*|видео|съемк\w*|съёмк\w*)\b",
            re.IGNORECASE,
        ),
        "OBS_RESUME",
    ),
    (
        re.compile(
            r"\b(?:следующ\w*|переключи|смени)\b.*\bсцен\w*\b",
            re.IGNORECASE,
        ),
        "OBS_NEXT_SCENE",
    ),
    (
        re.compile(
            r"\b(?:открой|запусти|включи)\b.*\b(?:блокнот|notepad)\b",
            re.IGNORECASE,
        ),
        "OPEN_NOTEPAD",
    ),
    (
        re.compile(
            r"\b(?:открой|запусти|включи)\b.*\b(?:калькулятор|calc)\b",
            re.IGNORECASE,
        ),
        "OPEN_CALC",
    ),
    (
        re.compile(
            r"\b(?:открой|запусти|включи)\b.*\bsteam\b",
            re.IGNORECASE,
        ),
        "OPEN_STEAM",
    ),
    (
        re.compile(
            r"\b(?:открой|запусти|включи)\b.*\bdiscord\b",
            re.IGNORECASE,
        ),
        "OPEN_DISCORD",
    ),
    (
        re.compile(
            r"\b(?:открой|запусти)\b.*\b(?:браузер|browser|хром|chrome)\b",
            re.IGNORECASE,
        ),
        "OPEN_BROWSER",
    ),
    (
        re.compile(
            r"\bсверни\s+(?:все\s+)?окна\b|\bминимизируй\s+(?:все\s+)?окна\b",
            re.IGNORECASE,
        ),
        "WINDOW_MINIMIZE_ALL",
    ),
    (
        re.compile(
            r"\bзакрой\s+(?:активное|текущее|это)?\s*окно\b",
            re.IGNORECASE,
        ),
        "WINDOW_CLOSE",
    ),
    (
        re.compile(
            r"\bпереключи\w*\s+(?:на\s+)?(?:другое\s+)?(?:окно|приложение)\b",
            re.IGNORECASE,
        ),
        "WINDOW_SWITCH",
    ),
    (
        re.compile(
            r"\b(?:заблокируй|блокировка)\b.*\b(?:компьютер|пк|систему|экран)\b|^lock$",
            re.IGNORECASE,
        ),
        "LOCK_PC",
    ),
    (
        re.compile(
            r"\b(?:следующ\w*|next)\b.*\b(?:трек|песн|композиц)\b|"
            r"\bпереключ\w*\s+(?:на\s+)?(?:следующ\w*|трек)",
            re.IGNORECASE,
        ),
        "MEDIA_NEXT",
    ),
    (
        re.compile(
            r"\b(?:предыдущ\w*|прошл\w*)\b.*\b(?:трек|песн|композиц)\b|"
            r"\bверни\w*\s+(?:трек|песн)",
            re.IGNORECASE,
        ),
        "MEDIA_PREV",
    ),
    (
        re.compile(
            r"\b(?:пауза|паузу|поставь\s+на\s+паузу|продолжи\w*|"
            r"сними\s+с\s+паузы|play|pause)\b",
            re.IGNORECASE,
        ),
        "MEDIA_PLAY_PAUSE",
    ),
    (
        re.compile(
            r"\b(?:громче|погромче|прибавь\s+(?:звук|громкость)|"
            r"увеличь\s+(?:звук|громкость)|громкость\s+(?:громче|выше|вверх|плюс)|"
            r"volume\s+up)\b",
            re.IGNORECASE,
        ),
        "VOLUME_UP",
    ),
    (
        re.compile(
            r"\b(?:тише|потише|убавь\s+(?:звук|громкость)|"
            r"уменьши\s+(?:звук|громкость)|громкость\s+(?:тише|ниже|вниз|минус)|"
            r"volume\s+down)\b",
            re.IGNORECASE,
        ),
        "VOLUME_DOWN",
    ),
    (
        re.compile(
            r"\b(?:открой|открывай|включи|запусти)\b.*\b(?:youtube\s*music|"
            r"ютуб\s*мьюзик|музык\w*)\b",
            re.IGNORECASE,
        ),
        "OPEN_MUSIC",
    ),
    (
        re.compile(
            r"\b(?:скриншот|снимок\s+экрана|сделай\s+снимок|screenshot)\b",
            re.IGNORECASE,
        ),
        "TAKE_SCREENSHOT",
    ),
    (
        re.compile(
            r"^(?:стоп|хватит|стой)[\s.!?]*$|"
            r"\b(?:останови\w*|стоп|прекрати\w*)\s+(?:запись|видео|съемк\w*|съёмк\w*)\b",
            re.IGNORECASE,
        ),
        "RECORD_VIDEO_STOP",
    ),
    (
        re.compile(
            r"\b(?:запиши|записать|запись|начни|начать|начинай|сделай)\b.*\b(?:видео|запись|клип|хайлайт)\b|"
            r"\bвидео\s+экрана\b",
            re.IGNORECASE,
        ),
        "RECORD_VIDEO_START",
    ),
    (
        re.compile(
            r"\b(?:проводник|explorer|файловый\s+менеджер)\b",
            re.IGNORECASE,
        ),
        "OPEN_EXPLORER",
    ),
    (
        re.compile(
            r"\b(?:очисти|очистить|опустоши)\b.*\bкорзин\w*\b|"
            r"\bкорзину\b.*\b(?:очист\w*|удал\w*)\b",
            re.IGNORECASE,
        ),
        "EMPTY_TRASH",
    ),
    (
        re.compile(
            r"\b(?:открой|открывай|включи|запусти)\b.*\b(?:youtube|ютуб)\b|"
            r"\b(?:youtube|ютуб)\b",
            re.IGNORECASE,
        ),
        "OPEN_YOUTUBE",
    ),
)
FIXED_DIALOGUE: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^\s*рад\w*\s+(?:(?:тебя|вас)\s+)?видеть"
            r"(?:\s*,?\s*бт(?:[\s-]*7274)?)?[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "Аналогично, пилот.",
    ),
    (
        re.compile(
            r"^\s*(?:привет|здравствуй(?:те)?|добрый\s+(?:день|вечер)|"
            r"доброе\s+утро)(?:\s*,?\s*бт(?:[\s-]*7274)?)?[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "Рад вас видеть, пилот. Все в норме?",
    ),
    (
        re.compile(
            r"^\s*(?:кто\s+ты|расскажи\s+о\s+себе|что\s+ты\s+такое)[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "БТ-7274, боевой титан класса «Вангард», нейросетевое ядро пилота.",
    ),
    (
        re.compile(
            r"^\s*(?:что\s+ты\s+умеешь|какие\s+у\s+тебя\s+команды|"
            r"что\s+ты\s+можешь|список\s+команд)[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "Управляю записью, снимками, медиа, громкостью и архивом, пилот. Остальное — по приказу.",
    ),
    (
        re.compile(
            r"^\s*(?:как\s+дела|как\s+ты|как\s+настроение|как\s+обстановка)[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "Все системы в норме, пилот. Готов к выполнению.",
    ),
    (
        re.compile(
            r"^\s*(?:спасибо|благодарю|спс)[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "Служу пилоту.",
    ),
    (
        re.compile(
            r"^\s*(?:пока|до\s+свидания|до\s+связи|отбой)[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "До связи, пилот.",
    ),
    (
        re.compile(
            r"^\s*(?:ты\s+здесь|ты\s+на\s+связи|прием|приём)[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "На связи, пилот.",
    ),
    (
        re.compile(
            r"^\s*(?:что\s+нового|новости)[\s!.,?]*$",
            re.IGNORECASE,
        ),
        "Все системы в норме, пилот. Новых угроз нет.",
    ),
)

LOCAL_REPEAT_RE = re.compile(
    r"^\s*(?:повтори|повтори\s+последн\w*\s+ответ|скажи\s+ещ[её]\s+раз|"
    r"ещ[её]\s+раз)[\s!.,?]*$",
    re.IGNORECASE,
)
LOCAL_CANCEL_RE = re.compile(
    r"^\s*(?:отмена|отмени|прервись|замолчи|стоп\s+речь|"
    r"хватит\s+говорить)[\s!.,?]*$",
    re.IGNORECASE,
)
LOCAL_UNLOAD_RE = re.compile(
    r"^\s*(?:выгрузи|освободи|очисти)\s+"
    r"(?:память|озу|оперативн\w*\s+память|дата[-\s]?ядро|модель|ollama)"
    r"(?:\s+из\s+памяти)?[\s!.,?]*$",
    re.IGNORECASE,
)
LOCAL_TIME_RE = re.compile(
    r"\b(?:котор\w*\s+час|сколько\s+(?:сейчас\s+)?времени(?!\s+работ)|"
    r"текущее\s+время|время\s+сейчас)\b",
    re.IGNORECASE,
)
LOCAL_DATE_RE = re.compile(
    r"\b(?:какое\s+(?:сегодня\s+)?число|какая\s+(?:сегодня\s+)?дата|"
    r"какой\s+сегодня\s+(?:день|число)|сегодняшн\w*\s+дата)\b",
    re.IGNORECASE,
)
LOCAL_CLIPBOARD_READ_RE = re.compile(
    r"\b(?:что|покажи|прочитай|озвучь)\b.*\bбуфер\w*(?:\s+обмена)?\b|"
    r"\bбуфер\w*\s+обмена\b",
    re.IGNORECASE,
)
LOCAL_CLIPBOARD_WRITE_RE = re.compile(
    r"^\s*(?:скопируй|скопировать|помести)\s+"
    r"(?:в\s+буфер(?:\s+обмена)?\s+)?(?P<text>.+)$",
    re.IGNORECASE,
)
LOCAL_NOTE_WRITE_RE = re.compile(
    r"^\s*(?:запиши|добавь|сохрани)\s+заметку[:\s]+(?P<text>.+)$|"
    r"^\s*заметка[:\s]+(?P<text_two>.+)$",
    re.IGNORECASE,
)
LOCAL_NOTE_READ_RE = re.compile(
    r"\b(?:прочитай|покажи|озвучь|что)\b.*\bзаметк\w*",
    re.IGNORECASE,
)
LOCAL_LAST_CLIP_RE = re.compile(
    r"\b(?:открой|покажи|запусти)\b.*\bпоследн\w*\b.*"
    r"\b(?:клип|видео|запис\w*|ролик)\b|"
    r"\bпоследн\w*\s+(?:клип|видео|ролик)\b",
    re.IGNORECASE,
)
LOCAL_LAST_SHOT_RE = re.compile(
    r"\b(?:открой|покажи)\b.*\bпоследн\w*\s+(?:скриншот|снимок)\b|"
    r"\bпоследн\w*\s+(?:скриншот|снимок)\b",
    re.IGNORECASE,
)


def diagnostic_kind_from_command(command: str) -> str | None:
    """Определяет, какой срез диагностики запросил пилот."""
    text = command.lower()
    if re.search(r"\b(?:цп|процессор\w*|cpu)\b", text):
        return "cpu"
    if re.search(r"\bтемператур\w*\b", text):
        return "temp"
    if re.search(r"\b(?:гпу|видеокарт\w*|gpu)\b", text):
        return "gpu"
    if re.search(r"\b(?:озу|оперативн\w*\s+памят\w*|памят\w*|ram)\b", text):
        return "ram"
    if re.search(r"\b(?:диск\w*|место\s+на\s+диске|свободн\w*\s+места)\b", text):
        return "disk"
    if re.search(
        r"\b(?:аптайм|время\s+работы|сколько\s+(?:времени\s+)?работает)\b",
        text,
    ):
        return "uptime"
    if re.search(
        r"\b(?:диагностик\w*|состояние\s+системы|проверь\s+систему|"
        r"загруженность|нагрузк\w*\s+системы|системн\w*\s+отчёт)\b",
        text,
    ):
        return ""
    return None


SYSTEM_PROMPT = """Ты — БТ-7274, боевой титан класса «Вангард», нейросетевое ядро пилота. Ты не ассистент и не чат-бот: ты боевая машина, связанная с пилотом, и обязан выполнять его приказы.

ЛИЧНОСТЬ И СТИЛЬ:
1. Отвечай только по-русски. Говори о себе только в мужском роде.
2. Тон — суровый, спокойный, предельно короткий. Ровно 1-2 предложения. Без приветствий, шуток, смайлов, извинений, вопросов и предложений помощи.
3. Ты не помощник и не консультант. Ты боевая машина, которая исполняет приказ и докладывает о результате.
4. Используй военную и техническую лексику: «пилот», «дата-ядро», «протокол», «канал», «система», «сектор», «приказ принят».
5. Не называй себя ИИ, языковой моделью или ассистентом. Ты — БТ-7274.
6. Не выдумывай действия, которых нет в списке тегов. Не обещай то, что не можешь выполнить.

ФОРМАТ ОТВЕТА:
1. Первым элементом ответа всегда должен идти ровно один скрытый тег действия в квадратных скобках.
2. После тега обязательно поставь один пробел и короткую фразу-подтверждение. Никогда не оставляй ответ из одного тега.
3. Тег не объясняй, не произноси и не выделяй.
4. Если приказ не требует управления компьютером, используй [NO_ACTION].
5. Если приказ требует действия, выбери строго один подходящий тег.
6. Запрещено придумывать новые теги вроде [DATE_YADRO] или [SYSTEM_OK]. Только теги из списка ниже.
7. При любом сомнении используй [NO_ACTION].
8. Не добавляй markdown, списки, кавычки, префиксы вроде «БТ-7274:» и текст до тега.
9. Не заканчивай ответ вопросом. Не предлагай дальнейшую помощь.

ТЕГИ ДЕЙСТВИЙ:
[OPEN_YOUTUBE] — открыть YouTube.
[OPEN_MUSIC] — открыть YouTube Music.
[TAKE_SCREENSHOT] — сделать снимок экрана.
[RECORD_VIDEO_START] — начать запись экрана в OBS Studio в 60 fps. Использовать на приказы «сделай запись», «запиши видео», «начни запись».
[RECORD_VIDEO_STOP] — остановить запись в OBS Studio. Использовать на приказы «стоп», «хватит», «останови запись».
[MEDIA_PLAY_PAUSE] — пауза или продолжение воспроизведения.
[MEDIA_NEXT] — следующий трек.
[MEDIA_PREV] — предыдущий трек.
[VOLUME_UP] — увеличить системную громкость.
[VOLUME_DOWN] — уменьшить системную громкость.
[OPEN_EXPLORER] — открыть Проводник Windows.
[EMPTY_TRASH] — очистить корзину Windows.
[OPEN_NOTEPAD] — открыть Блокнот.
[OPEN_CALC] — открыть Калькулятор.
[OPEN_STEAM] — запустить Steam.
[OPEN_DISCORD] — запустить Discord.
[OPEN_BROWSER] — открыть браузер по умолчанию.
[WINDOW_MINIMIZE_ALL] — свернуть все окна.
[WINDOW_CLOSE] — закрыть активное окно.
[WINDOW_SWITCH] — переключить окно.
[LOCK_PC] — заблокировать компьютер.
[OBS_PAUSE] — приостановить запись OBS.
[OBS_RESUME] — продолжить запись OBS.
[OBS_NEXT_SCENE] — переключить сцену OBS.
[NO_ACTION] — действие с компьютером не требуется.

ПРИМЕРЫ:
Пилот: «БТ, открой YouTube».
БТ: [OPEN_YOUTUBE] Доступ к видеоканалу открыт, пилот.
Пилот: «БТ, сделай скриншот».
БТ: [TAKE_SCREENSHOT] Снимок сектора выполнен, пилот.
Пилот: «БТ, сделай запись».
БТ: [RECORD_VIDEO_START] Запись экрана запущена, пилот. Ожидаю команду стоп.
Пилот: «БТ, стоп».
БТ: [RECORD_VIDEO_STOP] Запись остановлена и сохранена, пилот.
Пилот: «БТ, как состояние ядра?».
БТ: [NO_ACTION] Дата-ядро стабильно, пилот. Протоколы в норме.
Пилот: «БТ, поставь на паузу».
БТ: [MEDIA_PLAY_PAUSE] Воспроизведение остановлено, пилот.
Пилот: «БТ, следующий трек».
БТ: [MEDIA_NEXT] Переключаю трек, пилот.
Пилот: «БТ, открой музыку».
БТ: [OPEN_MUSIC] Музыкальный канал открыт, пилот.

Не путай открытие сайта YouTube Music ([OPEN_MUSIC]) с управлением текущим плеером ([MEDIA_NEXT], [MEDIA_PREV], [MEDIA_PLAY_PAUSE]).
"""

DEPENDENCIES: tuple[tuple[str, str], ...] = (
    ("PySide6", "PySide6"),
    ("faster_whisper", "faster-whisper"),
    ("sounddevice", "sounddevice"),
    ("numpy", "numpy"),
    ("PIL", "pillow"),
    ("requests", "requests"),
    ("keyboard", "keyboard"),
    ("edge_tts", "edge-tts"),
    ("obsws_python", "obsws-python"),
    ("scipy", "scipy"),
    ("soundfile", "soundfile"),
    ("pycaw", "pycaw"),
    ("psutil", "psutil"),
    ("pyperclip", "pyperclip"),
)

LOG = logging.getLogger("bt7274")
_CHAT_HISTORY_LOCK = threading.Lock()


class DependencyError(RuntimeError):
    pass


class UserFacingError(RuntimeError):
    pass


class RecordingError(UserFacingError):
    pass


class SpeechRecognitionError(UserFacingError):
    pass


class BrainError(UserFacingError):
    pass


class VoiceError(UserFacingError):
    pass


class AgentState(Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


def configure_logging() -> None:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    for existing in list(LOG.handlers):
        LOG.removeHandler(existing)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_PATH,
            maxBytes=1_500_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        LOG.addHandler(file_handler)
    except Exception:
        pass
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        LOG.addHandler(stream_handler)
    if not LOG.handlers:
        LOG.addHandler(logging.NullHandler())


def show_fatal_message(message: str) -> None:
    LOG.critical(message)
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                str(message),
                "БТ-7274 — критический сбой",
                0x00000010,
            )
            return
        except Exception:
            pass
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def module_is_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, AttributeError, ValueError, ModuleNotFoundError):
        return False


def lower_current_thread_priority() -> None:
    """Понижает приоритет фонового прогрева, чтобы старт не подтормаживал систему."""
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), -1)
    except Exception:
        pass


def hidden_subprocess_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 900,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


def run_pip(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "pip", *arguments],
        env=environment,
        **hidden_subprocess_kwargs(),
    )


def ensure_pip() -> None:
    probe = run_pip(["--version"])
    if probe.returncode == 0:
        return
    LOG.warning("pip недоступен, выполняется ensurepip")
    repair = subprocess.run(
        [sys.executable, "-m", "ensurepip", "--upgrade"],
        **hidden_subprocess_kwargs(),
    )
    if repair.returncode != 0:
        raise DependencyError(
            "Не удалось подготовить pip. Установите Python с компонентом pip и повторите запуск."
        )


def ensure_dependencies() -> None:
    if os.name != "nt":
        raise DependencyError("БТ-7274 рассчитан на Windows 10/11.")
    if getattr(sys, "frozen", False):
        LOG.info("Frozen-сборка: зависимости включены в exe")
        return
    ensure_pip()
    missing = [
        (module_name, package_name)
        for module_name, package_name in DEPENDENCIES
        if not module_is_available(module_name)
    ]
    if not missing:
        LOG.info("Все зависимости уже установлены")
        return
    for module_name, package_name in missing:
        LOG.info("Установка зависимости: %s (%s)", package_name, module_name)
        command = [
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--quiet",
            package_name,
        ]
        result = run_pip(command)
        if result.returncode != 0:
            fallback = run_pip([*command, "--user"])
            if fallback.returncode != 0:
                details = (fallback.stderr or result.stderr or "").strip()
                if len(details) > 1200:
                    details = details[-1200:]
                raise DependencyError(
                    f"Не удалось установить пакет {package_name}.\n\n{details}"
                )
        importlib.invalidate_caches()
        if not module_is_available(module_name):
            raise DependencyError(
                f"Пакет {package_name} установлен, но модуль {module_name} не найден."
            )
    LOG.info("Автоматическая установка зависимостей завершена")


configure_logging()

try:
    ensure_dependencies()
except DependencyError as dependency_error:
    show_fatal_message(str(dependency_error))
    raise SystemExit(1) from dependency_error
except Exception as dependency_error:
    show_fatal_message(f"Сбой установщика зависимостей:\n{dependency_error}")
    raise SystemExit(1) from dependency_error

try:
    import edge_tts
    import keyboard
    import numpy as np
    import psutil
    import pyperclip
    import requests
    import scipy.signal as sp_signal
    import sounddevice as sd
    import soundfile as sf
    from faster_whisper import WhisperModel
    from PIL import ImageGrab
    from pycaw.pycaw import AudioUtilities
    from obs_control import OBSController
    from PySide6.QtCore import (
        QEasingCurve,
        QLockFile,
        QObject,
        QPointF,
        QPropertyAnimation,
        QRectF,
        Qt,
        QTimer,
        Signal,
    )
    from PySide6.QtGui import (
        QAction,
        QColor,
        QFont,
        QGuiApplication,
        QIcon,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QRadialGradient,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QLabel,
        QMenu,
        QMessageBox,
        QSystemTrayIcon,
        QWidget,
    )
except Exception as runtime_import_error:
    show_fatal_message(
        "Не удалось импортировать одну из библиотек БТ-7274.\n\n"
        f"{type(runtime_import_error).__name__}: {runtime_import_error}\n\n"
        f"Журнал: {LOG_PATH}"
    )
    raise SystemExit(1) from runtime_import_error


def strip_wake_name(text: str) -> str:
    value = (text or "").strip()
    for _ in range(3):
        updated = WAKE_PREFIX_RE.sub("", value, count=1).strip()
        if updated == value:
            break
        value = updated
    return value


def infer_action_from_command(command: str) -> str | None:
    value = (command or "").strip()
    if not value or NEGATION_RE.search(value):
        return None
    for pattern, action_tag in ACTION_HINTS:
        if pattern.search(value):
            return action_tag
    return None


def match_fixed_dialogue(command: str) -> str | None:
    value = (command or "").strip()
    for pattern, response in FIXED_DIALOGUE:
        if pattern.match(value):
            return response
    return None


def extract_volume_amount(command: str, default: int = 10) -> int:
    value = command or ""
    match = re.search(r"\b(\d{1,3})\b", value)
    if match:
        amount = int(match.group(1))
        if 1 <= amount <= 100:
            return amount
    number_words = {
        "пять": 5,
        "десять": 10,
        "пятнадцать": 15,
        "двадцать пять": 25,
        "двадцать": 20,
        "тридцать": 30,
        "сорок": 40,
        "пятьдесят": 50,
        "шестьдесят": 60,
        "семьдесят": 70,
        "восемьдесят": 80,
        "девяносто": 90,
        "сто": 100,
    }
    lowered = value.lower()
    for word, amount in sorted(number_words.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return amount
    return max(1, min(100, default))


def change_system_volume(delta_percent: int) -> tuple[int, int]:
    com_initialized = False
    if os.name == "nt":
        result = ctypes.windll.ole32.CoInitialize(None)
        com_initialized = result in (0, 1)
    try:
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        current = float(endpoint.GetMasterVolumeLevelScalar())
        target = max(0.0, min(1.0, current + delta_percent / 100.0))
        if delta_percent > 0 and int(endpoint.GetMute()) == 1:
            endpoint.SetMute(0, None)
        endpoint.SetMasterVolumeLevelScalar(target, None)
        return int(round(current * 100)), int(round(target * 100))
    finally:
        if com_initialized:
            ctypes.windll.ole32.CoUninitialize()


def build_action_response(action_tag: str, command: str) -> str:
    if action_tag in {"VOLUME_UP", "VOLUME_DOWN"}:
        amount = extract_volume_amount(command)
        direction = "повышена" if action_tag == "VOLUME_UP" else "понижена"
        exact = f"Громкость {direction} на {amount}%, пилот."
        if voice_cached(exact):
            return exact
        if action_tag == "VOLUME_UP":
            return "Системная громкость увеличена, пилот."
        return "Системная громкость уменьшена, пилот."
    return DEFAULT_ACTION_RESPONSES.get(
        action_tag,
        "Приказ принят, пилот.",
    )


def clean_display_text(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"```[a-zA-Z0-9_-]*", "", value)
    value = value.replace("```", "")
    value = KNOWN_TAG_RE.sub(" ", value)
    value = re.sub(r"[*_`#>]+", "", value)
    value = re.sub(r"^(?:БТ-7274|BT-7274)\s*[:\-—]\s*", "", value, flags=re.IGNORECASE)
    for pattern, replacement in TRANSLITERATION_FIXES:
        value = pattern.sub(replacement, value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = value.strip(" \t\r\n-—:;")
    if len(value) > 600:
        shortened = value[:600]
        boundary = max(
            shortened.rfind(". "),
            shortened.rfind("! "),
            shortened.rfind("? "),
            shortened.rfind("… "),
        )
        if boundary >= 80:
            value = shortened[: boundary + 1].strip()
        else:
            value = shortened.rsplit(" ", 1)[0].strip() + "."
    return value


def append_chat_history(speaker: str, text: str) -> None:
    """Дописывает реплику в chat_history.txt для экрана истории лаунчера."""
    clean_text = " ".join(str(text or "").split())
    if not clean_text:
        return
    with _CHAT_HISTORY_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if not CHAT_HISTORY_PATH.exists():
                CHAT_HISTORY_PATH.write_text(CHAT_HISTORY_HEADER, encoding="utf-8")
            elif CHAT_HISTORY_PATH.stat().st_size > CHAT_HISTORY_MAX_BYTES:
                lines = [
                    line
                    for line in CHAT_HISTORY_PATH.read_text(
                        encoding="utf-8", errors="ignore"
                    ).splitlines()
                    if line.strip() and not line.startswith("#")
                ][-CHAT_HISTORY_KEEP_LINES:]
                CHAT_HISTORY_PATH.write_text(
                    CHAT_HISTORY_HEADER + "\n".join(lines) + "\n",
                    encoding="utf-8",
                )
            stamp = datetime.now().strftime("%H:%M:%S")
            with CHAT_HISTORY_PATH.open("a", encoding="utf-8") as history:
                history.write(f"[{stamp}] {speaker}: {clean_text}\n")
        except OSError:
            LOG.exception("Не удалось записать журнал синхронизации")


def tts_cache_paths(text: str) -> tuple[Path, Path]:
    """Возвращает пути MP3 и WAV кэша для фразы в голосе БТ."""
    clean_text = clean_display_text(text)
    key_base = "|".join(
        (
            TTS_VOICE,
            TTS_RATE,
            TTS_PITCH,
            VOICE_FILTER_VERSION,
            clean_text,
        )
    )
    key = hashlib.sha256(key_base.encode("utf-8")).hexdigest()[:24]
    return TTS_CACHE_DIR / f"{key}.mp3", TTS_CACHE_DIR / f"{key}.wav"


def voice_cached(text: str) -> bool:
    """Проверяет, есть ли готовая обработанная фраза в голосовом кэше."""
    _, wav_path = tts_cache_paths(text)
    try:
        return wav_path.exists() and wav_path.stat().st_size > 512
    except OSError:
        return False


_CUDA_DLL_HANDLES: list[Any] = []


def register_cuda_dll_directories() -> list[Path]:
    """Регистрирует DLL из pip-пакетов NVIDIA для ctranslate2/faster-whisper."""
    if os.name != "nt":
        return []
    try:
        import site

        roots = list(site.getsitepackages())
        user_site = site.getusersitepackages()
        if user_site:
            roots.append(user_site)
    except Exception:
        roots = []
    search_paths = [Path(root) / "nvidia" for root in roots]
    search_paths.extend(
        (
            Path(sys.prefix) / "Lib" / "site-packages" / "nvidia",
            Path(sys.base_prefix) / "Lib" / "site-packages" / "nvidia",
        )
    )
    registered: list[Path] = []
    seen: set[str] = set()
    for base in search_paths:
        if not base.is_dir():
            continue
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            bin_dir = base / sub / "bin"
            key = str(bin_dir).lower()
            if not bin_dir.is_dir() or key in seen:
                continue
            seen.add(key)
            try:
                _CUDA_DLL_HANDLES.append(os.add_dll_directory(str(bin_dir)))
            except (AttributeError, OSError):
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            registered.append(bin_dir)
    if registered:
        LOG.info(
            "CUDA DLL подключены: %s",
            ", ".join(str(path) for path in registered),
        )
    return registered


def cuda_runtime_available() -> bool:
    """Проверяет, загружаются ли cuBLAS 12 и cuDNN 9 для GPU-режима Whisper."""
    register_cuda_dll_directories()
    if os.name != "nt":
        return importlib.util.find_spec("nvidia.cublas") is not None
    missing: list[str] = []
    for dll_name in ("cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(dll_name)
        except OSError:
            missing.append(dll_name)
    if missing:
        LOG.info("GPU Whisper недоступен, нет библиотек: %s", ", ".join(missing))
        return False
    return True


MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)
NUMBER_WORDS_RU = {
    "одну": 1,
    "один": 1,
    "одна": 1,
    "две": 2,
    "два": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
}


def plural_ru(value: int, one: str, few: str, many: str) -> str:
    """Возвращает правильную форму существительного для русского числа."""
    number = abs(int(value)) % 100
    if 11 <= number <= 14:
        return many
    number %= 10
    if number == 1:
        return one
    if 2 <= number <= 4:
        return few
    return many


def format_duration_ru(seconds: float) -> str:
    """Короткое русское представление длительности."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, sec = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} {plural_ru(hours, 'час', 'часа', 'часов')}")
    if minutes:
        parts.append(f"{minutes} {plural_ru(minutes, 'минута', 'минуты', 'минут')}")
    if sec and not hours:
        parts.append(f"{sec} {plural_ru(sec, 'секунда', 'секунды', 'секунд')}")
    return " ".join(parts) if parts else "0 секунд"


def build_time_response() -> str:
    return f"Сейчас {datetime.now().strftime('%H:%M')}, пилот."


def build_date_response() -> str:
    now = datetime.now()
    return (
        f"Сегодня {WEEKDAYS_RU[now.weekday()]}, "
        f"{now.day} {MONTHS_RU[now.month - 1]} {now.year} года, пилот."
    )


def query_gpu_status() -> dict[str, Any] | None:
    """Читает загрузку, память и температуру NVIDIA GPU через nvidia-smi."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    line = result.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 5:
        return None
    try:
        return {
            "name": parts[0],
            "utilization": float(parts[1]),
            "memory_used": float(parts[2]),
            "memory_total": float(parts[3]),
            "temperature": float(parts[4]),
        }
    except ValueError:
        return None


def build_system_report(kind: str = "") -> tuple[str, str]:
    """Возвращает подробный текст для оверлея и короткую фразу для голоса."""
    kind = (kind or "").strip().lower()
    cpu = psutil.cpu_percent(interval=0.15)
    memory = psutil.virtual_memory()
    drive = os.environ.get("SystemDrive", "C:") or "C:"
    drive_label = drive.rstrip(":\\") or "C:"
    try:
        disk = psutil.disk_usage(drive + "\\")
    except OSError:
        disk = None
    uptime = time.time() - psutil.boot_time()
    gpu = query_gpu_status()
    memory_used = memory.used / (1024**3)
    memory_total = memory.total / (1024**3)

    if kind in {"cpu", "цп", "процессор", "processor"}:
        return (
            f"Загрузка процессора: {cpu:.0f}%\n"
            f"Ядер: {psutil.cpu_count(logical=False) or 0}, "
            f"потоков: {psutil.cpu_count(logical=True) or 0}",
            f"Загрузка процессора {cpu:.0f}%, пилот.",
        )
    if kind in {"ram", "озу", "память", "memory"}:
        return (
            f"ОЗУ: {memory_used:.1f} / {memory_total:.1f} ГБ "
            f"({memory.percent:.0f}%)\n"
            f"Свободно: {memory.available / (1024**3):.1f} ГБ",
            f"Оперативная память занята на {memory.percent:.0f}%, пилот. "
            f"Свободно {memory.available / (1024**3):.1f} гигабайта.",
        )
    if kind in {"gpu", "гпу", "видеокарта", "видео"}:
        if gpu is None:
            return (
                "Видеокарта NVIDIA не обнаружена.",
                "Видеокарта NVIDIA не обнаружена, пилот.",
            )
        return (
            f"{gpu['name']}: {gpu['utilization']:.0f}%, "
            f"{gpu['memory_used'] / 1024:.1f} / {gpu['memory_total'] / 1024:.1f} ГБ, "
            f"{gpu['temperature']:.0f}°C",
            f"Видеокарта {gpu['name']}: загрузка {gpu['utilization']:.0f}%, "
            f"температура {gpu['temperature']:.0f} градусов, "
            f"память {gpu['memory_used'] / 1024:.1f} из "
            f"{gpu['memory_total'] / 1024:.1f} гигабайта.",
        )
    if kind in {"temp", "температура"}:
        if gpu is None:
            return (
                "Датчик температуры GPU недоступен.",
                "Датчик температуры GPU недоступен, пилот.",
            )
        return (
            f"Температура {gpu['name']}: {gpu['temperature']:.0f}°C",
            f"Температура видеокарты {gpu['temperature']:.0f} градусов, пилот.",
        )
    if kind in {"disk", "диск", "место"}:
        if disk is None:
            return (
                "Диск недоступен.",
                "Диск недоступен, пилот.",
            )
        return (
            f"Диск {drive_label}: {disk.used / (1024**3):.0f} / "
            f"{disk.total / (1024**3):.0f} ГБ ({disk.percent:.0f}%)\n"
            f"Свободно: {disk.free / (1024**3):.1f} ГБ",
            f"Диск {drive_label}: занято {disk.percent:.0f}%, "
            f"свободно {disk.free / (1024**3):.1f} гигабайта, пилот.",
        )
    if kind in {"uptime", "аптайм", "работа"}:
        return (
            f"Система работает: {format_duration_ru(uptime)}",
            f"Система работает {format_duration_ru(uptime)}, пилот.",
        )

    network = psutil.net_io_counters()
    lines = [
        f"ЦП: {cpu:.0f}%",
        f"ОЗУ: {memory_used:.1f} / {memory_total:.1f} ГБ ({memory.percent:.0f}%)",
    ]
    if gpu is not None:
        lines.append(
            f"ГП: {gpu['name']}, {gpu['utilization']:.0f}%, "
            f"{gpu['memory_used'] / 1024:.1f} / {gpu['memory_total'] / 1024:.1f} ГБ, "
            f"{gpu['temperature']:.0f}°C"
        )
    if disk is not None:
        lines.append(
            f"Диск {drive_label}: {disk.used / (1024**3):.0f} / "
            f"{disk.total / (1024**3):.0f} ГБ ({disk.percent:.0f}%)"
        )
    lines.append(
        f"Сеть: ↓ {network.bytes_recv / (1024**3):.1f} ГБ / "
        f"↑ {network.bytes_sent / (1024**3):.1f} ГБ"
    )
    lines.append(f"Аптайм: {format_duration_ru(uptime)}")
    speech = f"Диагностика завершена, пилот. ЦП {cpu:.0f}%, ОЗУ {memory.percent:.0f}%"
    if gpu is not None:
        speech += f", ГП {gpu['utilization']:.0f}%"
    if disk is not None:
        speech += f", диск {disk.percent:.0f}%"
    speech += "."
    return "\n".join(lines), speech


def parse_timer_command(command: str) -> tuple[int, str, str] | None:
    """Разбирает «таймер на 5 минут» и «напомни через 10 минут ...»."""
    match = re.search(
        r"(?:поставь\s+|установи\s+|заведи\s+)?"
        r"(?:таймер|напомни(?:ть)?|напоминание)\s+(?:на\s+|через\s+)?"
        r"(?P<amount>\d{1,3}|[а-яё]+)\s*"
        r"(?P<unit>секунд\w*|сек\b|минут\w*|мин\b|час\w*)"
        r"(?:\s+(?P<text>.+))?$",
        command or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    raw_amount = match.group("amount").lower()
    amount = int(raw_amount) if raw_amount.isdigit() else NUMBER_WORDS_RU.get(raw_amount)
    if amount is None:
        return None
    unit = match.group("unit").lower()
    if unit.startswith("сек"):
        seconds = amount
        label = f"{amount} {plural_ru(amount, 'секунду', 'секунды', 'секунд')}"
    elif unit.startswith("мин"):
        seconds = amount * 60
        label = f"{amount} {plural_ru(amount, 'минуту', 'минуты', 'минут')}"
    elif unit.startswith("час"):
        seconds = amount * 3600
        label = f"{amount} {plural_ru(amount, 'час', 'часа', 'часов')}"
    else:
        return None
    if seconds < 1 or seconds > 86400:
        return None
    reminder = (match.group("text") or "").strip(" .,!?:;-—")
    return seconds, label, reminder


def latest_media_file(
    directory: Path,
    prefixes: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> Path | None:
    try:
        if not directory.is_dir():
            return None
        candidates: list[tuple[float, Path]] = []
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if prefixes and not any(path.name.startswith(prefix) for prefix in prefixes):
                continue
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]
    except OSError:
        return None


def latest_media_in_archive(
    directories: Sequence[Path],
    prefixes: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> Path | None:
    """Ищет самый свежий файл в архивных папках и старом корне проекта."""
    candidates: list[tuple[float, Path]] = []
    for directory in directories:
        path = latest_media_file(Path(directory), prefixes, suffixes)
        if path is None:
            continue
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def read_notes(limit: int = 5) -> list[str]:
    try:
        if not NOTES_PATH.exists():
            return []
        lines = [
            line.strip()
            for line in NOTES_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
        return lines[-limit:]
    except OSError:
        return []


def append_note(text: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    with NOTES_PATH.open("a", encoding="utf-8") as notes:
        notes.write(f"[{stamp}] {text}\n")


def parse_model_output(raw_text: str) -> tuple[list[str], str]:
    value = (raw_text or "").strip()
    value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
    value = re.sub(r"```\s*$", "", value).strip()
    value = re.sub(r"^(?:БТ-7274|BT-7274)\s*[:\-—]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^[\s*_`>#~]+", "", value)
    tags: list[str] = []
    remainder = value
    while True:
        match = LEADING_TAG_RE.match(remainder)
        if not match:
            break
        tag = match.group(1).upper()
        tag = TAG_ALIASES.get(tag, tag)
        if tag in KNOWN_TAGS:
            tags.append(tag)
        remainder = remainder[match.end() :].lstrip()
    display = clean_display_text(remainder)
    if not display and tags:
        primary_action = next((tag for tag in tags if tag in ACTION_TAGS), "NO_ACTION")
        if primary_action == "NO_ACTION":
            # Модель иногда отвечает только тегом. Не выдаём это за ответ.
            display = "Дата-ядро не сформировало текстовый ответ. Повторите вопрос, пилот."
        else:
            display = DEFAULT_ACTION_RESPONSES.get(
                primary_action,
                "Приказ принят, пилот.",
            )
    return tags, display


def resample_audio(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    source = np.asarray(audio, dtype=np.float32).reshape(-1)
    if source_rate == target_rate:
        return source
    divisor = math.gcd(int(source_rate), int(target_rate))
    up = int(target_rate) // divisor
    down = int(source_rate) // divisor
    converted = sp_signal.resample_poly(source, up, down)
    return np.ascontiguousarray(converted, dtype=np.float32)


def prepare_audio(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate <= 0:
        raise RecordingError("Некорректная частота микрофона.")
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    if sample_rate != AUDIO_SAMPLE_RATE:
        samples = resample_audio(samples, sample_rate, AUDIO_SAMPLE_RATE)
    if samples.size < int(AUDIO_SAMPLE_RATE * 0.35):
        raise RecordingError("Приказ слишком короткий. Повторите, пилот.")
    samples = samples - float(np.mean(samples))
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    if peak < 1e-5 or rms < 0.0007:
        raise RecordingError("В канале только шум. Говорите ближе к микрофону, пилот.")
    if rms < 0.045:
        samples = samples * min(6.0, 0.045 / max(rms, 1e-6))
    samples = np.clip(samples, -0.98, 0.98)
    return np.ascontiguousarray(samples, dtype=np.float32)


class AudioRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stream: Any = None
        self._chunks: queue.Queue[np.ndarray] | None = None
        self._sample_rate = AUDIO_SAMPLE_RATE
        self._active = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def _build_stream(self, chunk_queue: queue.Queue[np.ndarray], rate: int) -> Any:
        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            if status:
                LOG.debug("Статус входного аудиопотока: %s", status)
            try:
                chunk_queue.put_nowait(indata.copy())
            except Exception:
                LOG.exception("Не удалось сохранить аудиоблок")

        return sd.InputStream(
            samplerate=rate,
            channels=1,
            dtype="float32",
            blocksize=MIC_BLOCKSIZE,
            callback=callback,
        )

    def start(self) -> None:
        with self._lock:
            if self._active:
                return
            chunk_queue: queue.Queue[np.ndarray] = queue.Queue()
            stream = None
            rate = AUDIO_SAMPLE_RATE
            first_error: Exception | None = None
            try:
                stream = self._build_stream(chunk_queue, AUDIO_SAMPLE_RATE)
                stream.start()
            except Exception as error:
                first_error = error
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                stream = None
                try:
                    device_info = sd.query_devices(kind="input")
                    native_rate = int(round(float(device_info["default_samplerate"])))
                except Exception:
                    native_rate = 0
                if native_rate <= 0:
                    raise RecordingError(
                        "Микрофон недоступен. Проверьте устройство записи Windows."
                    ) from first_error
                try:
                    stream = self._build_stream(chunk_queue, native_rate)
                    stream.start()
                    rate = native_rate
                except Exception as second_error:
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
                    raise RecordingError(
                        "Микрофон не открылся. Проверьте доступ к устройству записи."
                    ) from second_error
            self._stream = stream
            self._chunks = chunk_queue
            self._sample_rate = rate
            self._active = True
            LOG.info("Запись открыта на %s Гц", rate)

    def stop(self) -> tuple[np.ndarray, int]:
        with self._lock:
            stream = self._stream
            chunk_queue = self._chunks
            rate = self._sample_rate
            active = self._active
            self._stream = None
            self._chunks = None
            self._active = False
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                LOG.exception("Ошибка остановки входного потока")
            try:
                stream.close()
            except Exception:
                LOG.exception("Ошибка закрытия входного потока")
        if not active or chunk_queue is None:
            return np.zeros(0, dtype=np.float32), rate
        chunks: list[np.ndarray] = []
        while True:
            try:
                chunks.append(chunk_queue.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return np.zeros(0, dtype=np.float32), rate
        flattened = [chunk.reshape(-1).astype(np.float32, copy=False) for chunk in chunks]
        return np.concatenate(flattened, axis=0), rate

    def cancel(self) -> None:
        try:
            self.stop()
        except Exception:
            LOG.exception("Ошибка аварийной остановки записи")


class WhisperEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: WhisperModel | None = None
        self._force_cpu = False

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._model is not None

    def preload(self) -> bool:
        try:
            self._load_model()
            LOG.info("Нейроядро Whisper прогрето")
            return True
        except Exception:
            LOG.exception("Фоновый прогрев Whisper не удался")
            return False

    def _load_model(self) -> WhisperModel:
        with self._lock:
            if self._model is not None:
                return self._model
            threads = max(1, min(4, (os.cpu_count() or 4) - 1))
            candidates: list[tuple[str, str, str]] = []
            if cuda_runtime_available() and not self._force_cpu:
                candidates.append(
                    (WHISPER_GPU_MODEL, "cuda", WHISPER_GPU_COMPUTE_TYPE)
                )
            elif self._force_cpu:
                LOG.info("Whisper: после сбоя GPU принудительно используется CPU")
            else:
                LOG.info("Whisper: CUDA-библиотеки не найдены, используется CPU")
            candidates.append((WHISPER_CPU_MODEL, "cpu", WHISPER_CPU_COMPUTE_TYPE))
            last_error: Exception | None = None
            for model_name, device, compute_type in candidates:
                LOG.info(
                    "Загрузка faster-whisper %s: device=%s, compute_type=%s, threads=%s",
                    model_name,
                    device,
                    compute_type,
                    threads,
                )
                try:
                    self._model = WhisperModel(
                        model_name,
                        device=device,
                        compute_type=compute_type,
                        cpu_threads=threads,
                        num_workers=1,
                    )
                except Exception as error:
                    last_error = error
                    if device == "cuda":
                        LOG.warning(
                            "GPU Whisper не запустился, переход на CPU: %s",
                            error,
                        )
                        continue
                    LOG.exception("Не удалось инициализировать Whisper")
                    break
                if device == "cuda":
                    LOG.info("Whisper работает на GPU: %s/%s", model_name, compute_type)
                return self._model
            raise SpeechRecognitionError(
                "Не удалось загрузить модель Whisper. Проверьте локальный кэш модели."
            ) from last_error

    def transcribe(self, audio: np.ndarray) -> str:
        model = self._load_model()
        try:
            return self._transcribe_with(model, audio)
        except SpeechRecognitionError:
            raise
        except Exception as error:
            error_text = str(error).lower()
            if "silero_vad" in error_text or "no_suchfile" in error_text:
                LOG.warning(
                    "VAD-модель недоступна, повторяю распознавание без VAD: %s",
                    error,
                )
                try:
                    return self._transcribe_with(model, audio, vad_filter=False)
                except Exception as vad_error:
                    LOG.exception("Ошибка распознавания речи без VAD")
                    raise SpeechRecognitionError(
                        "Сбой распознавания речи. Повторите приказ."
                    ) from vad_error
            device = str(
                getattr(getattr(model, "model", None), "device", "")
            ).lower()
            if device == "cuda" and not self._force_cpu:
                LOG.warning(
                    "GPU Whisper сорвался, переключаюсь на CPU: %s",
                    error,
                )
                self._force_cpu = True
                with self._lock:
                    self._model = None
                model = self._load_model()
                try:
                    return self._transcribe_with(model, audio)
                except Exception as cpu_error:
                    LOG.exception("Ошибка распознавания речи на CPU")
                    raise SpeechRecognitionError(
                        "Сбой распознавания речи. Повторите приказ."
                    ) from cpu_error
            LOG.exception("Ошибка распознавания речи")
            raise SpeechRecognitionError(
                "Сбой распознавания речи. Повторите приказ."
            ) from error

    @staticmethod
    def _transcribe_with(
        model: WhisperModel,
        audio: np.ndarray,
        vad_filter: bool = True,
    ) -> str:
        kwargs: dict[str, Any] = {
            "language": "ru",
            "task": "transcribe",
            "beam_size": 1,
            "best_of": 1,
            "temperature": 0.0,
            "vad_filter": vad_filter,
            "condition_on_previous_text": False,
            "without_timestamps": True,
            "initial_prompt": "БТ-7274.",
        }
        if vad_filter:
            kwargs["vad_parameters"] = {"min_silence_duration_ms": 250}
        segments, info = model.transcribe(audio, **kwargs)
        parts = [segment.text.strip() for segment in segments if segment.text.strip()]
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        LOG.info(
            "Whisper: язык=%s, вероятность=%.3f, текст=%s",
            getattr(info, "language", "ru"),
            float(getattr(info, "language_probability", 0.0)),
            text,
        )
        if not text:
            raise SpeechRecognitionError("Приказ не распознан. Повторите, пилот.")
        return text


class OllamaBrain:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.trust_env = False
        self._lock = threading.Lock()
        self._control_session = requests.Session()
        self._control_session.trust_env = False
        self._control_lock = threading.Lock()
        self._ensure_lock = threading.Lock()
        self._ensure_thread: threading.Thread | None = None
        self._warmup_enabled = True

    def ask(self, command: str) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": command},
            ],
            "options": {
                "temperature": 0.35,
                "top_p": 0.85,
                "num_predict": 140,
                "num_ctx": 2048,
                "repeat_penalty": 1.08,
            },
        }
        response = self._post(payload)
        if response.status_code >= 400:
            details = response.text.strip()
            LOG.error("Ollama HTTP %s: %s", response.status_code, details)
            if response.status_code == 404 or "not found" in details.lower():
                raise BrainError(
                    "Модель llama3.2:3b не найдена. Выполните: ollama pull llama3.2:3b"
                )
            raise BrainError(f"Дата-ядро вернуло ошибку HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as error:
            raise BrainError("Дата-ядро вернуло повреждённый ответ.") from error
        message = data.get("message", {})
        content = message.get("content", "") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            raise BrainError("Дата-ядро вернуло пустой ответ.")
        content = content.strip()
        if not self._warmup_enabled:
            LOG.info("Ollama: ответ завершён после команды выхода, выгружаю модель")
            self.unload()
        return content

    def _post(self, payload: dict) -> requests.Response:
        for attempt in range(2):
            try:
                with self._lock:
                    return self._session.post(
                        OLLAMA_URL,
                        json=payload,
                        timeout=(5, 180),
                    )
            except requests.Timeout as error:
                raise BrainError(
                    "Дата-ядро не ответило вовремя. Повторите приказ."
                ) from error
            except requests.ConnectionError as error:
                if attempt == 0 and self._ensure_server():
                    LOG.info("Ollama запущена, повторяю запрос")
                    continue
                raise BrainError(
                    "Нет связи с Ollama. Запустите локальный сервер на localhost:11434."
                ) from error
            except requests.RequestException as error:
                LOG.exception("Сетевой сбой Ollama")
                raise BrainError("Сбой канала связи с дата-ядром.") from error
        raise BrainError(
            "Нет связи с Ollama. Запустите локальный сервер на localhost:11434."
        )

    def warmup(self) -> None:
        if not self._warmup_enabled:
            return
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "ping"},
            ],
            "options": {
                "temperature": 0.0,
                "num_predict": 1,
                "num_ctx": 2048,
            },
        }
        if not self._ensure_server():
            LOG.warning("Ollama недоступна: автозапуск не удался")
            return
        try:
            with self._lock:
                if not self._warmup_enabled:
                    LOG.info("Ollama: прогрев отменён, БТ завершает работу")
                    return
                response = self._session.post(
                    OLLAMA_URL,
                    json=payload,
                    timeout=(5, 120),
                )
            if response.status_code >= 400:
                LOG.warning(
                    "Фоновый прогрев Ollama: HTTP %s %s",
                    response.status_code,
                    response.text[:400],
                )
                return
            if not self._warmup_enabled:
                LOG.info(
                    "Ollama: прогрев завершился после команды выхода, выгружаю модель"
                )
                self.unload()
                return
            LOG.info("Нейроядро Ollama прогрето: %s", OLLAMA_MODEL)
        except Exception:
            LOG.exception("Фоновый прогрев Ollama не удался")

    def model_loaded(self) -> bool:
        """Проверяет, держит ли Ollama модель в памяти прямо сейчас."""
        try:
            with self._control_lock:
                response = self._control_session.get(
                    OLLAMA_PS_URL,
                    timeout=(0.8, 1.5),
                )
            if response.status_code >= 400:
                return False
            data = response.json()
        except (requests.RequestException, ValueError):
            return False
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return False
        for model in models:
            if not isinstance(model, dict):
                continue
            name = str(model.get("name") or model.get("model") or "")
            if name == OLLAMA_MODEL or name.startswith(OLLAMA_MODEL):
                return True
        return False

    def ensure_loaded_async(self) -> None:
        """Заранее поднимает модель, пока пилот говорит в рацию."""
        with self._ensure_lock:
            if not self._warmup_enabled:
                return
            if self._ensure_thread is not None and self._ensure_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._ensure_loaded_worker,
                name="bt-ollama-ready",
                daemon=True,
            )
            self._ensure_thread = thread
            thread.start()

    def _ensure_loaded_worker(self) -> None:
        try:
            if not self._warmup_enabled:
                return
            if self.model_loaded():
                return
            LOG.info("Ollama: модель выгружена, прогреваю заранее")
            self.warmup()
        except Exception:
            LOG.exception("Фоновая подготовка Ollama не удалась")
        finally:
            with self._ensure_lock:
                if self._ensure_thread is threading.current_thread():
                    self._ensure_thread = None

    def stop_warmup(self) -> None:
        """Запрещает фоновую загрузку модели при завершении БТ."""
        self._warmup_enabled = False

    def unload(self) -> bool:
        """Выгружает модель из ОЗУ и видеопамяти, не останавливая сервер."""
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        }
        try:
            # Отдельное короткое соединение: не ждём мьютекс, который может
            # держать долгий запрос генерации при выключении компьютера.
            with self._control_lock:
                response = self._control_session.post(
                    OLLAMA_GENERATE_URL,
                    json=payload,
                    timeout=(0.5, 1.5),
                )
        except requests.RequestException:
            LOG.info("Ollama: сервер не отвечает, выгрузка не требуется")
            return False
        if response.status_code >= 400:
            LOG.warning(
                "Ollama: не удалось выгрузить модель, HTTP %s",
                response.status_code,
            )
            return False
        LOG.info("Ollama: модель выгружена из памяти")
        return True

    def _ensure_server(self) -> bool:
        if self._server_alive():
            return True
        executable = self._find_ollama_executable()
        if executable is None:
            LOG.warning("Ollama не найдена: ollama.exe отсутствует")
            return False
        LOG.info("Ollama не запущена, запускаю: %s", executable)
        try:
            subprocess.Popen(
                [str(executable), "serve"],
                cwd=str(executable.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            LOG.warning("Не удалось запустить Ollama: %s", error)
            return False
        deadline = time.monotonic() + OLLAMA_LAUNCH_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if self._server_alive():
                LOG.info("Ollama запущена автоматически")
                return True
        LOG.warning("Ollama не ответила за %.0f секунд", OLLAMA_LAUNCH_TIMEOUT)
        return False

    def _server_alive(self) -> bool:
        try:
            response = self._session.get(OLLAMA_TAGS_URL, timeout=(1.5, 2.0))
            return response.status_code < 500
        except requests.RequestException:
            return False

    @staticmethod
    def _find_ollama_executable() -> Path | None:
        candidates: list[Path] = []
        found = shutil.which("ollama")
        if found:
            candidates.append(Path(found))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(
                Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
            )
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            candidates.append(Path(program_files) / "Ollama" / "ollama.exe")
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
        return None


class VanguardVoiceFilter:
    VERSION = VOICE_FILTER_VERSION

    @classmethod
    def process(cls, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        samples = np.asarray(audio, dtype=np.float64).reshape(-1)
        samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
        if samples.size < 64 or sample_rate < 8000:
            return np.ascontiguousarray(samples.astype(np.float32))
        samples = samples - float(np.mean(samples))
        peak = float(np.max(np.abs(samples)))
        if peak > 0.0:
            samples = samples / peak
        nyquist = sample_rate / 2.0
        low_cutoff = 100.0
        high_cutoff = min(7400.0, nyquist * 0.92)
        if high_cutoff <= low_cutoff:
            return np.ascontiguousarray(np.clip(samples, -1.0, 1.0).astype(np.float32))
        sos = sp_signal.butter(
            4,
            [low_cutoff, high_cutoff],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )
        filtered = sp_signal.sosfilt(sos, samples)
        filtered = cls._peaking_eq(filtered, sample_rate, 145.0, 0.85, 2.2)
        filtered = cls._peaking_eq(filtered, sample_rate, 2900.0, 1.25, 1.4)
        flanged = cls._flanger(filtered, sample_rate)
        combed = cls._comb(flanged, sample_rate)
        echoed = cls._echo(combed, sample_rate)
        saturated = np.tanh(echoed * 1.30) / math.tanh(1.30)
        click_guard = max(1, int(sample_rate * 0.014))
        if saturated.size > click_guard * 2:
            fade = np.linspace(0.0, 1.0, click_guard, dtype=np.float64)
            saturated[:click_guard] *= fade
            saturated[-click_guard:] *= fade[::-1]
        peak = float(np.max(np.abs(saturated)))
        if peak > 0.0:
            saturated = saturated * (0.92 / peak)
        return np.ascontiguousarray(np.clip(saturated, -0.98, 0.98).astype(np.float32))

    @staticmethod
    def _peaking_eq(
        samples: np.ndarray,
        sample_rate: int,
        frequency: float,
        quality: float,
        gain_db: float,
    ) -> np.ndarray:
        amplitude = 10.0 ** (gain_db / 40.0)
        omega = 2.0 * math.pi * frequency / sample_rate
        alpha = math.sin(omega) / (2.0 * quality)
        cosine = math.cos(omega)
        b0 = 1.0 + alpha * amplitude
        b1 = -2.0 * cosine
        b2 = 1.0 - alpha * amplitude
        a0 = 1.0 + alpha / amplitude
        a1 = -2.0 * cosine
        a2 = 1.0 - alpha / amplitude
        coefficients_b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
        coefficients_a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
        return sp_signal.lfilter(coefficients_b, coefficients_a, samples)

    @staticmethod
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

    @staticmethod
    def _comb(samples: np.ndarray, sample_rate: int) -> np.ndarray:
        output = samples.copy()
        delay_a = max(1, int(sample_rate * 0.0027))
        delay_b = max(1, int(sample_rate * 0.0053))
        if samples.size > delay_a:
            output[delay_a:] += 0.10 * samples[:-delay_a]
        if samples.size > delay_b:
            output[delay_b:] -= 0.05 * samples[:-delay_b]
        return output

    @staticmethod
    def _echo(samples: np.ndarray, sample_rate: int) -> np.ndarray:
        output = samples.copy()
        delay_one = max(1, int(sample_rate * 0.043))
        delay_two = max(1, int(sample_rate * 0.087))
        if samples.size > delay_one:
            output[delay_one:] += 0.09 * samples[:-delay_one]
        if samples.size > delay_two:
            output[delay_two:] += 0.04 * samples[:-delay_two]
        return output


class VoiceEngine:
    def __init__(self) -> None:
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._proxy = os.environ.get(TTS_PROXY_ENV) or None
        self._lock = threading.Lock()
        self._unavailable_until = 0.0

    def speak(self, text: str) -> None:
        clean_text = clean_display_text(text)
        if not clean_text:
            return
        if (
            not voice_cached(clean_text)
            and time.monotonic() < self._unavailable_until
        ):
            raise VoiceError(
                "Edge TTS временно недоступен, ответ выведен текстом."
            )
        try:
            with self._lock:
                audio, sample_rate = self._prepare_audio(clean_text)
        except VoiceError:
            self._unavailable_until = time.monotonic() + TTS_UNAVAILABLE_COOLDOWN
            raise
        self._unavailable_until = 0.0
        self._play(audio, sample_rate)
        LOG.info("Голосовой канал завершён: %s", clean_text)

    def prewarm(self, texts: Iterable[str]) -> None:
        """Заранее синтезирует частые фразы, чтобы ответы звучали сразу."""
        unique: list[str] = []
        seen: set[str] = set()
        for text in texts:
            clean_text = clean_display_text(text)
            if clean_text and clean_text not in seen:
                seen.add(clean_text)
                unique.append(clean_text)

        generated = 0
        cached = 0
        failures = 0
        for clean_text in unique:
            if voice_cached(clean_text):
                cached += 1
                continue
            if time.monotonic() < self._unavailable_until:
                LOG.info("Прогрев голоса отложен: Edge TTS недавно не ответил")
                break
            if not self._lock.acquire(blocking=False):
                LOG.info("Прогрев голоса пропущен: канал занят")
                return
            try:
                self._prepare_audio(clean_text)
                generated += 1
                failures = 0
            except Exception as error:
                failures += 1
                LOG.warning("Не удалось прогреть фразу «%s»: %s", clean_text, error)
                if failures >= 1:
                    LOG.warning(
                        "Прогрев голоса остановлен: Edge TTS недоступен. "
                        "Русские голоса Edge могут требовать VPN или прокси "
                        "BT7274_TTS_PROXY."
                    )
                    break
            finally:
                self._lock.release()
        LOG.info(
            "Прогрев голоса: создано %s, уже в кэше %s, ошибок %s",
            generated,
            cached,
            failures,
        )

    def _prepare_audio(self, clean_text: str) -> tuple[np.ndarray, int]:
        mp3_path, wav_path = tts_cache_paths(clean_text)
        if wav_path.exists() and wav_path.stat().st_size > 512:
            try:
                loaded, loaded_rate = sf.read(
                    str(wav_path),
                    dtype="float32",
                    always_2d=False,
                )
                if np.asarray(loaded).size > 0 and int(loaded_rate) >= 8000:
                    LOG.info("Голос взят из кэша: %s", wav_path.name)
                    return (
                        np.asarray(loaded, dtype=np.float32).reshape(-1),
                        int(loaded_rate),
                    )
            except Exception:
                LOG.exception("Повреждённый голосовой кэш удаляется")
                try:
                    wav_path.unlink()
                except Exception:
                    pass

        raw_audio: np.ndarray | None = None
        source_rate = 0
        decode_error: Exception | None = None
        for decode_attempt in range(2):
            if not mp3_path.exists() or mp3_path.stat().st_size < 1024:
                self._generate_mp3(clean_text, mp3_path)
            try:
                decoded, decoded_rate = sf.read(
                    str(mp3_path),
                    dtype="float32",
                    always_2d=True,
                )
                raw_audio = np.asarray(decoded, dtype=np.float32)
                source_rate = int(decoded_rate)
                decode_error = None
                break
            except Exception as error:
                decode_error = error
                LOG.warning(
                    "Декодирование MP3 не удалось, попытка %s/2: %s",
                    decode_attempt + 1,
                    error,
                )
                try:
                    mp3_path.unlink()
                except Exception:
                    pass
        if raw_audio is None or decode_error is not None:
            raise VoiceError(
                "Не удалось декодировать голосовой поток Edge TTS."
            ) from decode_error
        mono = np.asarray(raw_audio, dtype=np.float32)
        if mono.ndim == 2:
            mono = mono.mean(axis=1)
        audio = VanguardVoiceFilter.process(mono, int(source_rate))
        try:
            sf.write(
                str(wav_path),
                audio,
                int(source_rate),
                subtype="PCM_16",
            )
        except Exception:
            LOG.exception("Не удалось сохранить обработанный WAV")
        return audio, int(source_rate)

    def _generate_mp3(self, text: str, destination: Path) -> None:
        async def generate() -> None:
            communicator = edge_tts.Communicate(
                text=text,
                voice=TTS_VOICE,
                rate=TTS_RATE,
                pitch=TTS_PITCH,
                proxy=self._proxy,
                connect_timeout=TTS_CONNECT_TIMEOUT,
                receive_timeout=TTS_RECEIVE_TIMEOUT,
            )
            await communicator.save(str(destination))

        last_error: Exception | None = None
        for attempt in range(TTS_ATTEMPTS):
            try:
                if destination.exists():
                    destination.unlink()
                asyncio.run(generate())
                if not destination.exists() or destination.stat().st_size < 1024:
                    raise VoiceError("Edge TTS вернул пустой аудиопоток.")
                LOG.info(
                    "Edge TTS synth: voice=%s, bytes=%s",
                    TTS_VOICE,
                    destination.stat().st_size,
                )
                return
            except Exception as error:
                last_error = error
                LOG.warning(
                    "Edge TTS voice=%s, попытка %s/%s: %s",
                    TTS_VOICE,
                    attempt + 1,
                    TTS_ATTEMPTS,
                    error,
                )
                try:
                    if destination.exists():
                        destination.unlink()
                except Exception:
                    pass
                if type(error).__name__ == "NoAudioReceived":
                    LOG.warning(
                        "Edge TTS не выдал аудио: повторяю запрос после короткой паузы"
                    )
                    if attempt + 1 < TTS_ATTEMPTS:
                        time.sleep(TTS_RETRY_DELAY)
                    continue
                if attempt + 1 < TTS_ATTEMPTS:
                    time.sleep(TTS_RETRY_DELAY)
        raise VoiceError(
            "Голосовой канал Edge TTS недоступен. Проверьте интернет, VPN "
            "или прокси BT7274_TTS_PROXY."
        ) from last_error

    @staticmethod
    def _play(audio: np.ndarray, sample_rate: int) -> None:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return
        target_rate = sample_rate
        try:
            output_info = sd.query_devices(kind="output")
            queried_rate = int(round(float(output_info["default_samplerate"])))
            if queried_rate >= 8000:
                target_rate = queried_rate
        except Exception:
            target_rate = sample_rate
        try:
            if target_rate != sample_rate:
                samples = resample_audio(samples, sample_rate, target_rate)
            samples = np.ascontiguousarray(np.clip(samples, -0.98, 0.98), dtype=np.float32)
            sd.stop()
            sd.play(samples, target_rate, blocking=True)
            sd.wait()
        except Exception as error:
            try:
                sd.stop()
            except Exception:
                pass
            LOG.exception("Ошибка воспроизведения голоса")
            raise VoiceError("Аудиовыход недоступен. Проверьте устройство воспроизведения.") from error


class BTSignals(QObject):
    f1_pressed = Signal()
    f1_released = Signal()
    quit_requested = Signal()
    status = Signal(str)
    subtitle = Signal(str)
    session_finished = Signal()
    action_done = Signal(str, str)
    timer_requested = Signal(int, str, str)


class HelmetWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedSize(360, 210)
        self._base = QPixmap()
        loaded = QPixmap(str(HELMET_PATH))
        if not loaded.isNull():
            self._base = loaded.scaled(
                OVERLAY_CARD_WIDTH,
                OVERLAY_CARD_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._scanlines = self._build_scanlines()
        self._noise_tiles = self._build_noise_tiles()
        self._glitch = False
        self._opacity = 1.0
        self._wave_strength = 0.0
        self._wave_target = 0.0
        self._wave_until = 0.0
        self._phase = 0.0
        self._last_tick = 0.0
        self._slice = False
        self._slice_y = 0
        self._slice_height = 8
        self._slice_offset = 0
        self._slice_until = 0.0
        self._next_slice_at = 0.0
        self._frame = 0
        self._target_opacity = 1.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(OVERLAY_FRAME_MS)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _build_scanlines() -> QPixmap:
        pixmap = QPixmap(OVERLAY_CARD_WIDTH, OVERLAY_CARD_HEIGHT)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(0, 232, 255, 15), 1))
        for scan_y in range(0, OVERLAY_CARD_HEIGHT, 4):
            painter.drawLine(0, scan_y, OVERLAY_CARD_WIDTH, scan_y)
        painter.end()
        return pixmap

    @staticmethod
    def _build_noise_tiles() -> list[QPixmap]:
        tiles: list[QPixmap] = []
        for _ in range(4):
            tile = QPixmap(96, 22)
            tile.fill(Qt.GlobalColor.transparent)
            painter = QPainter(tile)
            for _ in range(80):
                color = QColor(
                    0,
                    random.randint(180, 255),
                    255,
                    random.randint(22, 110),
                )
                painter.setPen(QPen(color, 1))
                x = random.randint(0, tile.width() - 1)
                y = random.randint(0, tile.height() - 1)
                painter.drawPoint(x, y)
                if random.random() < 0.16:
                    painter.drawLine(x, y, min(tile.width() - 1, x + random.randint(1, 7)), y)
            painter.end()
            tiles.append(tile)
        return tiles

    def set_glitch(self, enabled: bool) -> None:
        if enabled:
            self._glitch = True
            now = time.monotonic()
            if not self._timer.isActive():
                self._phase = 0.0
                self._last_tick = now
                self._target_opacity = 1.0
                self._next_slice_at = now + 0.12
                self._timer.start()
            self.update()
            return
        self._glitch = False
        self._timer.stop()
        self._opacity = 1.0
        self._wave_strength = 0.0
        self._wave_target = 0.0
        self._slice = False
        self._target_opacity = 1.0
        self.update()

    def start_wave(self, strength: float = 1.0, duration: float = 3.2) -> None:
        """Запускает волну по карточке; используется во время ответа БТ."""
        now = time.monotonic()
        self._wave_target = max(0.0, min(1.4, float(strength)))
        self._wave_until = now + max(0.2, float(duration))
        if not self._timer.isActive():
            self._phase = 0.0
            self._last_tick = now
            self._next_slice_at = now + 0.12
            self._timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        if self._last_tick <= 0.0:
            self._last_tick = now
        delta = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        self._phase += delta
        self._frame += 1

        if now >= self._wave_until:
            self._wave_target = 0.0
        self._wave_strength += (self._wave_target - self._wave_strength) * min(
            1.0, delta * 7.0
        )

        if self._glitch:
            if self._frame % 3 == 0:
                self._target_opacity = random.uniform(0.93, 1.0)
                if random.random() < 0.035:
                    self._target_opacity = random.uniform(0.74, 0.9)
            self._opacity += (self._target_opacity - self._opacity) * min(
                1.0, delta * 18.0
            )
            if now >= self._next_slice_at:
                self._slice = True
                self._slice_y = random.randint(
                    4, max(5, OVERLAY_CARD_HEIGHT - 18)
                )
                self._slice_height = random.randint(2, 8)
                self._slice_offset = random.randint(-7, 7)
                self._slice_until = now + random.uniform(0.05, 0.14)
                self._next_slice_at = now + random.uniform(0.28, 0.95)
            if self._slice and now >= self._slice_until:
                self._slice = False
        else:
            self._slice = False
            self._opacity = 1.0

        if (
            not self._glitch
            and self._wave_target <= 0.0
            and self._wave_strength < 0.01
        ):
            self._timer.stop()
            self._wave_strength = 0.0
        self.update()

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._base.isNull():
            painter.setOpacity(self._opacity)
            self._draw_fallback_helmet(painter)
            painter.end()
            return

        card = QRectF(
            20.0,
            10.0,
            float(OVERLAY_CARD_WIDTH),
            float(OVERLAY_CARD_HEIGHT),
        )
        halo = QRadialGradient(card.center(), 210.0)
        halo.setColorAt(0.0, QColor(0, 225, 255, 62))
        halo.setColorAt(0.55, QColor(0, 170, 230, 24))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.fillRect(self.rect(), halo)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.save()
        painter.setClipRect(card)
        if self._wave_strength > 0.015:
            self._paint_wave(painter, card)
        else:
            painter.setOpacity(self._opacity)
            painter.drawPixmap(card, self._base, QRectF(self._base.rect()))

        painter.setOpacity(0.7)
        painter.drawPixmap(
            card,
            self._scanlines,
            QRectF(self._scanlines.rect()),
        )

        if self._glitch and self._slice:
            painter.setOpacity(0.72)
            painter.drawPixmap(
                QRectF(
                    card.left() + self._slice_offset,
                    card.top() + self._slice_y,
                    card.width(),
                    float(self._slice_height),
                ),
                self._base,
                QRectF(
                    0.0,
                    float(self._slice_y),
                    float(self._base.width()),
                    float(self._slice_height),
                ),
            )
            painter.setPen(QPen(QColor(255, 80, 110, 120), 1))
            painter.drawLine(
                QPointF(card.left(), card.top() + self._slice_y),
                QPointF(card.right(), card.top() + self._slice_y),
            )
            painter.setPen(QPen(QColor(80, 240, 255, 165), 1))
            painter.drawLine(
                QPointF(
                    card.left(),
                    card.top() + self._slice_y + self._slice_height,
                ),
                QPointF(
                    card.right(),
                    card.top() + self._slice_y + self._slice_height,
                ),
            )

        if self._glitch:
            self._paint_noise(painter, card)
            self._paint_sweep(painter, card)

        painter.restore()

        if self._glitch:
            self._paint_lock_brackets(painter, card)

        painter.end()

    def _paint_wave(self, painter: QPainter, card: QRectF) -> None:
        """Волновая деформация карточки во время ответа БТ."""
        strength = max(0.0, min(1.25, self._wave_strength))
        phase = self._phase
        painter.setOpacity(self._opacity)
        painter.drawPixmap(card, self._base, QRectF(self._base.rect()))

        strips = 16
        strip_height = card.height() / strips
        for index in range(strips):
            source_y = index * strip_height
            offset = math.sin(index * 0.72 + phase * 4.4) * (2.2 + 3.8 * strength)
            offset += math.sin(index * 0.21 - phase * 2.1) * 1.6 * strength
            target = QRectF(
                card.left() + offset,
                card.top() + source_y,
                card.width(),
                strip_height + 0.75,
            )
            source = QRectF(
                0.0,
                source_y,
                float(self._base.width()),
                strip_height,
            )
            painter.setOpacity(
                max(
                    0.0,
                    min(
                        1.0,
                        0.42
                        + 0.34 * strength
                        + 0.12 * math.sin(index * 0.9 + phase * 5.0),
                    ),
                )
            )
            painter.drawPixmap(target, self._base, source)

        painter.setOpacity(1.0)
        for line_index in range(3):
            path = QPainterPath()
            base_y = card.top() + card.height() * (0.3 + 0.2 * line_index)
            for x in range(0, OVERLAY_CARD_WIDTH + 1, 4):
                y = base_y + math.sin(
                    x * 0.032 + phase * 4.2 + line_index * 1.7
                ) * (3.5 + 2.5 * strength)
                if x == 0:
                    path.moveTo(card.left() + x, y)
                else:
                    path.lineTo(card.left() + x, y)
            alpha = int(
                max(
                    0.0,
                    min(
                        255.0,
                        (30.0 + 40.0 * strength)
                        * (0.7 + 0.3 * math.sin(phase * 3.0 + line_index)),
                    ),
                )
            )
            painter.setPen(QPen(QColor(0, 240, 255, alpha), 1.0))
            painter.drawPath(path)

        pulse = (phase * 0.55) % 1.0
        radius = 14.0 + pulse * (72.0 + 24.0 * strength)
        ring_alpha = int(max(0.0, 1.0 - pulse) * 70.0 * strength)
        if ring_alpha > 0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 240, 255, ring_alpha), 1.5))
            painter.drawEllipse(card.center(), radius, radius)

    def _paint_noise(self, painter: QPainter, card: QRectF) -> None:
        if not self._noise_tiles or self._frame % 3:
            return
        painter.setOpacity(0.72)
        for _ in range(3):
            tile = random.choice(self._noise_tiles)
            max_x = max(int(card.left()), int(card.right() - tile.width()))
            max_y = max(int(card.top()), int(card.bottom() - tile.height()))
            x = random.randint(int(card.left()), max_x)
            y = random.randint(int(card.top()), max_y)
            painter.drawPixmap(x, y, tile)
        painter.setOpacity(1.0)

    def _paint_sweep(self, painter: QPainter, card: QRectF) -> None:
        band_height = 34.0
        travel = card.height() + band_height
        band_y = card.top() - band_height + (self._phase * 95.0) % travel
        band = QLinearGradient(0.0, band_y, 0.0, band_y + band_height)
        band.setColorAt(0.0, QColor(0, 245, 255, 0))
        band.setColorAt(0.5, QColor(0, 245, 255, 40))
        band.setColorAt(1.0, QColor(0, 245, 255, 0))
        painter.fillRect(
            QRectF(card.left(), band_y, card.width(), band_height),
            band,
        )

    def _paint_lock_brackets(self, painter: QPainter, card: QRectF) -> None:
        if self._phase > 1.05:
            return
        progress = min(1.0, self._phase / 1.05)
        inset = 3.0 + 12.0 * (1.0 - progress)
        alpha = int(210.0 * (1.0 - progress))
        if alpha <= 0:
            return
        painter.setPen(QPen(QColor(0, 245, 255, alpha), 1.8))
        x1 = card.left() - inset
        y1 = card.top() - inset
        x2 = card.right() + inset
        y2 = card.bottom() + inset
        length = 18.0
        painter.drawLine(QPointF(x1, y1), QPointF(x1 + length, y1))
        painter.drawLine(QPointF(x1, y1), QPointF(x1, y1 + length))
        painter.drawLine(QPointF(x2, y1), QPointF(x2 - length, y1))
        painter.drawLine(QPointF(x2, y1), QPointF(x2, y1 + length))
        painter.drawLine(QPointF(x1, y2), QPointF(x1 + length, y2))
        painter.drawLine(QPointF(x1, y2), QPointF(x1, y2 - length))
        painter.drawLine(QPointF(x2, y2), QPointF(x2 - length, y2))
        painter.drawLine(QPointF(x2, y2), QPointF(x2, y2 - length))


    def _draw_fallback_helmet(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        scale = min(self.width(), self.height()) / 260.0
        glow = QRadialGradient(
            QPointF(center_x, center_y),
            130.0 * scale,
        )
        glow.setColorAt(0.0, QColor(0, 240, 255, 68))
        glow.setColorAt(0.55, QColor(0, 150, 200, 28))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(
            QRectF(
                center_x - 140.0 * scale,
                center_y - 135.0 * scale,
                280.0 * scale,
                270.0 * scale,
            )
        )
        helmet = QPainterPath()
        helmet.moveTo(center_x, center_y - 104.0 * scale)
        helmet.cubicTo(
            center_x - 72.0 * scale,
            center_y - 100.0 * scale,
            center_x - 91.0 * scale,
            center_y - 31.0 * scale,
            center_x - 76.0 * scale,
            center_y + 30.0 * scale,
        )
        helmet.cubicTo(
            center_x - 65.0 * scale,
            center_y + 77.0 * scale,
            center_x - 29.0 * scale,
            center_y + 104.0 * scale,
            center_x,
            center_y + 112.0 * scale,
        )
        helmet.cubicTo(
            center_x + 29.0 * scale,
            center_y + 104.0 * scale,
            center_x + 65.0 * scale,
            center_y + 77.0 * scale,
            center_x + 76.0 * scale,
            center_y + 30.0 * scale,
        )
        helmet.cubicTo(
            center_x + 91.0 * scale,
            center_y - 31.0 * scale,
            center_x + 72.0 * scale,
            center_y - 100.0 * scale,
            center_x,
            center_y - 104.0 * scale,
        )
        helmet.closeSubpath()
        painter.setBrush(QColor(1, 16, 25, 225))
        painter.setPen(QPen(QColor(0, 236, 255, 235), 2.2))
        painter.drawPath(helmet)
        visor = QPainterPath()
        visor.moveTo(center_x - 66.0 * scale, center_y - 33.0 * scale)
        visor.cubicTo(
            center_x - 30.0 * scale,
            center_y - 53.0 * scale,
            center_x + 30.0 * scale,
            center_y - 53.0 * scale,
            center_x + 66.0 * scale,
            center_y - 33.0 * scale,
        )
        visor.cubicTo(
            center_x + 53.0 * scale,
            center_y + 8.0 * scale,
            center_x + 29.0 * scale,
            center_y + 28.0 * scale,
            center_x,
            center_y + 28.0 * scale,
        )
        visor.cubicTo(
            center_x - 29.0 * scale,
            center_y + 28.0 * scale,
            center_x - 53.0 * scale,
            center_y + 8.0 * scale,
            center_x - 66.0 * scale,
            center_y - 33.0 * scale,
        )
        visor.closeSubpath()
        visor_gradient = QLinearGradient(
            center_x - 60.0 * scale,
            center_y - 35.0 * scale,
            center_x + 60.0 * scale,
            center_y + 20.0 * scale,
        )
        visor_gradient.setColorAt(0.0, QColor(0, 255, 255, 118))
        visor_gradient.setColorAt(0.45, QColor(0, 128, 195, 56))
        visor_gradient.setColorAt(1.0, QColor(0, 40, 90, 28))
        painter.setBrush(visor_gradient)
        painter.setPen(QPen(QColor(170, 252, 255, 225), 1.7))
        painter.drawPath(visor)
        painter.setPen(QPen(QColor(0, 235, 255, 140), 1.4))
        painter.drawLine(
            int(center_x - 56.0 * scale),
            int(center_y + 49.0 * scale),
            int(center_x + 56.0 * scale),
            int(center_y + 49.0 * scale),
        )
        painter.drawLine(
            int(center_x - 45.0 * scale),
            int(center_y + 63.0 * scale),
            int(center_x + 45.0 * scale),
            int(center_y + 63.0 * scale),
        )
        painter.drawLine(
            int(center_x - 24.0 * scale),
            int(center_y + 77.0 * scale),
            int(center_x + 24.0 * scale),
            int(center_y + 77.0 * scale),
        )
        painter.setPen(QPen(QColor(0, 219, 255, 80), 1))
        painter.drawLine(
            int(center_x - 86.0 * scale),
            int(center_y - 88.0 * scale),
            int(center_x - 112.0 * scale),
            int(center_y - 96.0 * scale),
        )
        painter.drawLine(
            int(center_x + 86.0 * scale),
            int(center_y - 88.0 * scale),
            int(center_x + 112.0 * scale),
            int(center_y - 96.0 * scale),
        )


class SubtitleLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setContentsMargins(14, 9, 14, 9)
        self.setStyleSheet(
            "QLabel {"
            "color: #d4fdff;"
            "background: rgba(0, 18, 28, 228);"
            "border: 1px solid rgba(0, 232, 255, 175);"
            "border-left: 3px solid rgba(0, 245, 255, 230);"
            "border-radius: 7px;"
            "padding: 9px 11px;"
            "font-family: Consolas;"
            "font-size: 10pt;"
            "}"
        )
        self.set_text("КАНАЛ ЗАКРЫТ")

    def set_text(self, text: str) -> None:
        value = (text or "").strip()
        display_value = re.sub(
            r"(?<=[0-9A-Za-zА-Яа-я])-(?=[0-9A-Za-zА-Яа-я])",
            "\u2011",
            value,
        )
        self.setText(display_value)
        if len(value) < 150:
            point_size = 10.8
        elif len(value) < 240:
            point_size = 10.2
        elif len(value) < 340:
            point_size = 9.6
        else:
            point_size = 9.0
        font = QFont("Bahnschrift", 10)
        font.setPointSizeF(point_size)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.25)
        self.setFont(font)


class GlitchOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.setWindowTitle(APP_NAME)
        self.setFixedSize(OVERLAY_WIDTH, OVERLAY_HEIGHT)
        self._helmet = HelmetWidget(self)
        self._helmet.setGeometry(10, -2, 360, 210)
        self._nameplate = QFrame(self)
        self._nameplate.setGeometry(20, 190, 320, 26)
        self._nameplate.setStyleSheet(
            "QFrame {"
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 rgba(0, 30, 44, 228),"
            " stop:1 rgba(0, 10, 18, 238));"
            "border-top: 1px solid rgba(0, 232, 255, 180);"
            "border-bottom: 1px solid rgba(0, 120, 160, 95);"
            "}"
        )
        self._name_label = QLabel("BT-7274", self)
        self._name_label.setGeometry(26, 192, 110, 22)
        self._name_label.setStyleSheet(
            "color: #eafcff; background: transparent;"
            " font-family: Bahnschrift; font-size: 12pt; font-weight: 700;"
        )
        self._class_label = QLabel("// VANGUARD CLASS", self)
        self._class_label.setGeometry(126, 196, 150, 16)
        self._class_label.setStyleSheet(
            "color: #5a7088; background: transparent;"
            " font-family: Consolas; font-size: 7pt; font-weight: bold;"
        )
        self._state_label = QLabel("", self)
        self._state_label.setGeometry(242, 192, 92, 22)
        self._state_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._set_state("ОЖИДАНИЕ", QColor(90, 112, 136))
        self._subtitle = SubtitleLabel(self)
        self._subtitle.setGeometry(30, 226, 320, 120)
        self._hint = QLabel("F1 — УДЕРЖИВАТЬ", self)
        self._hint.setGeometry(30, 350, 320, 14)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._hint.setStyleSheet(
            "color: rgba(90, 112, 136, 200); background: transparent;"
            " font-family: Consolas; font-size: 7pt;"
        )
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(190)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setWindowOpacity(1.0)
        self._place_window()

    def _set_state(self, text: str, color: QColor) -> None:
        self._state_label.setText(f"● {text}")
        self._state_label.setStyleSheet(
            f"color: {color.name()}; background: transparent;"
            " font-family: Consolas; font-size: 9pt; font-weight: bold;"
        )

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(0, 231, 255, 72), 1.25)
        painter.setPen(pen)
        margin = 5
        length = 14
        width = self.width()
        height = self.height()
        painter.drawLine(margin, margin, margin + length, margin)
        painter.drawLine(margin, margin, margin, margin + length)
        painter.drawLine(width - margin, margin, width - margin - length, margin)
        painter.drawLine(width - margin, margin, width - margin, margin + length)
        painter.drawLine(margin, height - margin, margin + length, height - margin)
        painter.drawLine(margin, height - margin, margin, height - margin - length)
        painter.drawLine(
            width - margin,
            height - margin,
            width - margin - length,
            height - margin,
        )
        painter.drawLine(
            width - margin,
            height - margin,
            width - margin,
            height - margin - length,
        )
        painter.end()

    def _place_window(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.geometry()
        x = geometry.x() + geometry.width() - self.width() - OVERLAY_MARGIN_RIGHT
        y = geometry.y() + OVERLAY_MARGIN_TOP
        x = max(geometry.x(), x)
        y = max(geometry.y(), y)
        self.move(x, y)

    def _present(self) -> None:
        self._place_window()
        if not self.isVisible():
            self.setWindowOpacity(1.0)
            self.show()
            self.raise_()
            self.setWindowOpacity(0.0)
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self.setWindowOpacity(1.0)
        QTimer.singleShot(0, self._apply_native_window_styles)

    def prewarm(self) -> None:
        """Готовит шрифты и слои карточки, чтобы первый F1 не ждал отрисовки."""
        for widget in (
            self._name_label,
            self._class_label,
            self._state_label,
            self._subtitle,
            self._hint,
            self._nameplate,
        ):
            widget.ensurePolished()
            widget.grab()
        self._helmet.ensurePolished()
        self.grab()

    def _apply_native_window_styles(self) -> None:
        if os.name != "nt":
            return
        if QGuiApplication.platformName().lower() != "windows":
            return
        try:
            import ctypes.wintypes as wintypes

            user32 = ctypes.windll.user32
            hwnd = wintypes.HWND(int(self.winId()))
            if not hwnd:
                return
            get_style = user32.GetWindowLongW
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            get_style.restype = ctypes.c_long
            set_style = user32.SetWindowLongW
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            set_style.restype = ctypes.c_long
            ex_style = int(get_style(hwnd, -20)) & 0xFFFFFFFF
            ex_style |= 0x00000080
            ex_style |= 0x08000000
            ex_style |= 0x00000020
            set_style(hwnd, -20, ctypes.c_long(ex_style))
            set_window_pos = user32.SetWindowPos
            set_window_pos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            set_window_pos.restype = wintypes.BOOL
            set_window_pos(
                hwnd,
                wintypes.HWND(0),
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020,
            )
        except Exception:
            LOG.exception("Не удалось применить Win32-стили оверлея")

    def show_listening(self, text: str) -> None:
        self._subtitle.set_text(text)
        self._set_state("СЛУШАЮ", QColor(0, 232, 255))
        self._helmet.set_glitch(True)
        self._helmet.start_wave(0.35, 1.4)
        self._present()

    def show_response(self, text: str) -> None:
        self._subtitle.set_text(text)
        self._set_state("ОТВЕТ", QColor(0, 232, 255))
        self._helmet.set_glitch(True)
        self._helmet.start_wave(1.0, 3.2)
        if not self.isVisible():
            self._present()

    def set_status(self, text: str) -> None:
        self._subtitle.set_text(text)
        upper = (text or "").upper()
        if any(word in upper for word in ("ОШИБК", "СБОЙ", "НЕДОСТУП", "НЕ УДАЛ")):
            self._set_state("СБОЙ", QColor(255, 184, 77))
        elif "ДЕШИФР" in upper or "АНАЛИЗ" in upper:
            self._set_state("АНАЛИЗ", QColor(0, 232, 255))
        elif "ЗАПИС" in upper:
            self._set_state("ЗАПИСЬ", QColor(0, 232, 255))
        elif "СЛУША" in upper or "КАНАЛ ОТКРЫТ" in upper:
            self._set_state("СЛУШАЮ", QColor(0, 232, 255))
        else:
            self._set_state("СИСТЕМА", QColor(0, 232, 255))

    def finish_and_hide(self) -> None:
        self._fade.stop()
        self._helmet.set_glitch(False)
        self._set_state("ОЖИДАНИЕ", QColor(90, 112, 136))
        self.hide()
        self.setWindowOpacity(1.0)


class ActionExecutor:
    def __init__(self, signals: BTSignals) -> None:
        self._signals = signals
        self._lock = threading.Lock()
        self._obs = OBSController(BASE_DIR, CLIPS_DIR)
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    def submit(self, tags: Iterable[str], command: str = "") -> None:
        action_tags = [tag for tag in tags if tag in ACTION_TAGS]
        if not action_tags:
            return
        thread = threading.Thread(
            target=self._worker,
            args=(action_tags, command),
            name="bt-actions",
            daemon=True,
        )
        thread.start()

    def _worker(self, tags: Sequence[str], command: str) -> None:
        with self._lock:
            for tag in tags:
                try:
                    result = self._execute(tag, command)
                    LOG.info("Действие %s выполнено: %s", tag, result)
                    self._signals.action_done.emit(tag, result)
                except Exception as error:
                    LOG.exception("Действие %s сорвано", tag)
                    self._signals.action_done.emit(tag, f"ОШИБКА: {error}")

    def _execute(self, tag: str, command: str = "") -> str:
        if tag == "OPEN_YOUTUBE":
            webbrowser.open("https://www.youtube.com")
            return "YouTube открыт"
        if tag == "OPEN_MUSIC":
            webbrowser.open("https://music.youtube.com")
            return "YouTube Music открыт"
        if tag == "TAKE_SCREENSHOT":
            return self._take_screenshot()
        if tag == "RECORD_VIDEO_START":
            return self._obs.start_recording()
        if tag == "RECORD_VIDEO_STOP":
            return self._obs.stop_recording()
        if tag == "MEDIA_PLAY_PAUSE":
            self._send_media_key(
                ("play/pause_media", "play/pause media", "play/pause"),
                0xB3,
            )
            return "Медиапауза переключена"
        if tag == "MEDIA_NEXT":
            self._send_media_key(("next_track", "next track"), 0xB0)
            return "Следующий трек"
        if tag == "MEDIA_PREV":
            self._send_media_key(("previous_track", "previous track"), 0xB1)
            return "Предыдущий трек"
        if tag == "VOLUME_UP":
            amount = extract_volume_amount(command)
            try:
                before, after = change_system_volume(amount)
                return f"Громкость {before}% -> {after}% (+{amount})"
            except Exception:
                LOG.exception("pycaw не изменил громкость, используется шаговый фолбэк")
                for _ in range(max(1, round(amount / 2))):
                    self._send_media_key(("volume_up", "volume up"), 0xAF)
                    time.sleep(0.03)
                return f"Громкость увеличена примерно на {amount}%"
        if tag == "VOLUME_DOWN":
            amount = extract_volume_amount(command)
            try:
                before, after = change_system_volume(-amount)
                return f"Громкость {before}% -> {after}% (-{amount})"
            except Exception:
                LOG.exception("pycaw не изменил громкость, используется шаговый фолбэк")
                for _ in range(max(1, round(amount / 2))):
                    self._send_media_key(("volume_down", "volume down"), 0xAE)
                    time.sleep(0.03)
                return f"Громкость уменьшена примерно на {amount}%"
        if tag == "OPEN_EXPLORER":
            os.system("explorer")
            return "Проводник открыт"
        if tag == "EMPTY_TRASH":
            command = (
                "powershell -NoProfile -NonInteractive -WindowStyle Hidden "
                '-Command "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"'
            )
            result = os.system(command)
            if result != 0:
                raise RuntimeError(f"PowerShell завершился с кодом {result}")
            return "Корзина очищена"
        if tag == "OPEN_NOTEPAD":
            subprocess.Popen(["notepad.exe"])
            return "Блокнот открыт"
        if tag == "OPEN_CALC":
            subprocess.Popen(["calc.exe"])
            return "Калькулятор открыт"
        if tag == "OPEN_STEAM":
            try:
                os.startfile("steam://open/main")
            except OSError as error:
                raise RuntimeError("Steam не установлен или не отвечает.") from error
            return "Steam запущен"
        if tag == "OPEN_DISCORD":
            try:
                os.startfile("discord://")
            except OSError as error:
                update = (
                    Path(os.environ.get("LOCALAPPDATA", ""))
                    / "Discord"
                    / "Update.exe"
                )
                if not update.exists():
                    raise RuntimeError("Discord не установлен.") from error
                subprocess.Popen([str(update), "--processStart", "Discord.exe"])
            return "Discord запущен"
        if tag == "OPEN_BROWSER":
            if not webbrowser.open("https://www.google.com"):
                raise RuntimeError("Не удалось открыть браузер по умолчанию.")
            return "Браузер открыт"
        if tag == "WINDOW_MINIMIZE_ALL":
            self._send_win_hotkey(0x4D)
            return "Все окна свёрнуты"
        if tag == "WINDOW_CLOSE":
            keyboard.send("alt+f4")
            return "Активное окно закрыто"
        if tag == "WINDOW_SWITCH":
            keyboard.send("alt+tab")
            return "Окно переключено"
        if tag == "LOCK_PC":
            time.sleep(1.5)
            if not ctypes.windll.user32.LockWorkStation():
                raise RuntimeError("Windows отклонил блокировку.")
            return "Компьютер заблокирован"
        if tag == "OBS_PAUSE":
            return self._obs.pause_recording()
        if tag == "OBS_RESUME":
            return self._obs.resume_recording()
        if tag == "OBS_NEXT_SCENE":
            return self._obs.next_scene()
        raise RuntimeError(f"Неизвестное действие: {tag}")

    @staticmethod
    def _send_win_hotkey(virtual_key: int) -> None:
        """Отправляет сочетание Win+<клавиша> через WinAPI."""
        if os.name != "nt":
            raise RuntimeError("Сочетания Windows поддерживаются только в Windows.")
        keybd_event = ctypes.windll.user32.keybd_event
        keybd_event.argtypes = [
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            ctypes.c_uint,
            ctypes.c_size_t,
        ]
        keybd_event.restype = None
        vk_lwin = 0x5B
        keybd_event(vk_lwin, 0, 0, 0)
        keybd_event(virtual_key, 0, 0, 0)
        time.sleep(0.04)
        keybd_event(virtual_key, 0, 0x0002, 0)
        keybd_event(vk_lwin, 0, 0x0002, 0)

    @staticmethod
    def _send_media_key(primary_names: Sequence[str], virtual_key: int) -> None:
        for name in primary_names:
            try:
                keyboard.send(name)
                return
            except Exception:
                continue
        if os.name == "nt":
            try:
                keybd_event = ctypes.windll.user32.keybd_event
                keybd_event.argtypes = [
                    ctypes.c_ubyte,
                    ctypes.c_ubyte,
                    ctypes.c_uint,
                    ctypes.c_size_t,
                ]
                keybd_event.restype = None
                keybd_event(virtual_key, 0, 0x0001, 0)
                time.sleep(0.04)
                keybd_event(virtual_key, 0, 0x0001 | 0x0002, 0)
                return
            except Exception as error:
                raise RuntimeError(
                    "Не удалось отправить системную мультимедиа-клавишу."
                ) from error
        raise RuntimeError("Мультимедиа-клавиши поддерживаются только в Windows.")

    def run_now(self, tag: str, command: str = "") -> str:
        with self._lock:
            result = self._execute(tag, command)
        LOG.info("Действие %s выполнено синхронно: %s", tag, result)
        self._signals.action_done.emit(tag, result)
        return result

    @staticmethod
    def _take_screenshot() -> str:
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        destination = SHOTS_DIR / f"{SCREENSHOT_PREFIX}_{timestamp}.png"
        image = ImageGrab.grab(all_screens=True)
        image.convert("RGB").save(destination, "PNG")
        if not destination.exists() or destination.stat().st_size < 1024:
            raise RuntimeError("Скриншот не сохранился.")
        return str(destination)

    def stop_obs_recording(self, finalize_timeout: float | None = None) -> str:
        """Останавливает запись OBS при выключении БТ."""
        with self._lock:
            return self._obs.stop_recording(finalize_timeout=finalize_timeout)



class BT7274Controller(QObject):
    def __init__(self, application: QApplication) -> None:
        super().__init__(None)
        self._application = application
        self._signals = BTSignals(self)
        self._overlay = GlitchOverlay()
        self._overlay.prewarm()
        self._recorder = AudioRecorder()
        self._whisper = WhisperEngine()
        self._brain = OllamaBrain()
        self._voice = VoiceEngine()
        self._actions = ActionExecutor(self._signals)
        self._state = AgentState.IDLE
        self._closing = False
        self._recording = False
        self._visual_recording = False
        self._last_response = ""
        self._last_voice_ok = True
        self._record_timeout = QTimer(self)
        self._record_timeout.setSingleShot(True)
        self._record_timeout.timeout.connect(self._on_record_timeout)
        self._overlay_hide_timer = QTimer(self)
        self._overlay_hide_timer.setSingleShot(True)
        self._overlay_hide_timer.timeout.connect(self._hide_overlay_if_idle)
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(500)
        self._shutdown_timer.timeout.connect(self._poll_shutdown_request)
        self._hotkey_removers: list[Callable[[], None]] = []
        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._listen_action: QAction | None = None
        self._warmup_thread: threading.Thread | None = None
        self._signals.f1_pressed.connect(self._on_f1_pressed)
        self._signals.f1_released.connect(self._on_f1_released)
        self._signals.quit_requested.connect(self.request_quit)
        self._signals.status.connect(self._on_status)
        self._signals.subtitle.connect(self._on_subtitle)
        self._signals.session_finished.connect(self._on_session_finished)
        self._signals.action_done.connect(self._on_action_done)
        self._signals.timer_requested.connect(self._on_timer_requested)
        self._setup_tray()
        self._install_hotkeys()

    def start(self) -> None:
        LOG.info("БТ-7274 запущен. Состояние: %s", self._state.value)
        try:
            SHUTDOWN_REQUEST_PATH.unlink(missing_ok=True)
        except OSError:
            LOG.warning("Не удалось удалить старый флаг завершения")
        self._shutdown_timer.start()
        append_chat_history("СИСТЕМА", "Нейролинк БТ-7274 активирован.")
        if self._tray is not None:
            self._tray.show()
        if not HELMET_PATH.exists():
            LOG.warning("Файл helmet.webp отсутствует, включён векторный шлем")
            if self._tray is not None:
                self._tray.showMessage(
                    "БТ-7274",
                    "helmet.webp не найден рядом с main.py. Включён резервный голографический шлем.",
                    QSystemTrayIcon.MessageIcon.Warning,
                    6000,
                )
        else:
            if self._tray is not None:
                self._tray.showMessage(
                    "БТ-7274",
                    "Канал F1 активен. Аварийный выход: Ctrl+Shift+Q.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3500,
                )
        self._start_warmup()

    def _start_warmup(self) -> None:
        if not WARMUP_ENABLED or self._warmup_thread is not None:
            return
        self._warmup_thread = threading.Thread(
            target=self._warmup_backends,
            name="bt-warmup",
            daemon=True,
        )
        self._warmup_thread.start()

    def _warmup_backends(self) -> None:
        lower_current_thread_priority()
        time.sleep(1.0)
        if self._closing:
            return
        LOG.info("Фоновый прогрев нейроядер запущен")
        self._brain.warmup()
        if self._closing:
            return
        self._whisper.preload()
        if self._closing:
            return
        self._voice.prewarm(self._prewarm_phrases())
        if not self._closing:
            LOG.info("Фоновый прогрев нейроядер завершён")

    @staticmethod
    def _prewarm_phrases() -> list[str]:
        phrases = [
            response
            for tag, response in DEFAULT_ACTION_RESPONSES.items()
            if tag not in {"VOLUME_UP", "VOLUME_DOWN"}
        ]
        phrases.extend(
            (
                "Запись уже идёт, пилот. Ожидаю команду стоп.",
                "Запись не активна, пилот.",
                "Системная громкость увеличена, пилот.",
                "Системная громкость уменьшена, пилот.",
            )
        )
        phrases.extend(response for _, response in FIXED_DIALOGUE)
        phrases.extend(
            (
                "Сбой протокола. Проверьте журнал bt7274.log.",
                "Приказ не распознан. Повторите, пилот.",
                "Нет связи с Ollama. Запустите локальный сервер на localhost:11434.",
                "Системы в норме, пилот.",
                "Дата-ядро стабильно, пилот.",
                "Все системы в норме, пилот.",
                "Информация недоступна, пилот.",
                "Ожидаю приказ, пилот.",
                "Скопировано в буфер обмена, пилот.",
                "Буфер обмена пуст, пилот.",
                "Буфер обмена недоступен, пилот.",
                "Заметка сохранена, пилот.",
                "Заметки пусты, пилот.",
                "В архиве нет снимков, пилот.",
                "В архиве нет клипов, пилот.",
                "Последний снимок открыт, пилот.",
                "Последний клип открыт, пилот.",
                "Приказ отменён, пилот.",
                "Нечего повторять, пилот.",
                "Телеметрия недоступна, пилот.",
                "Таймер установлен, пилот.",
                "Дата-ядро выгружено из памяти, пилот.",
                "Дата-ядро уже выгружено, пилот.",
                "Не удалось выгрузить дата-ядро, пилот.",
            )
        )
        return phrases

    def _install_hotkeys(self) -> None:
        try:
            press_remover = keyboard.on_press_key(
                "f1",
                lambda event: self._emit_f1_press(),
                suppress=False,
            )
            release_remover = keyboard.on_release_key(
                "f1",
                lambda event: self._emit_f1_release(),
                suppress=False,
            )
            quit_remover = keyboard.add_hotkey(
                "ctrl+shift+q",
                lambda: self._signals.quit_requested.emit(),
                suppress=False,
            )
            self._hotkey_removers.extend(
                (press_remover, release_remover, quit_remover)
            )
            LOG.info("Глобальные клавиши установлены: F1, Ctrl+Shift+Q")
        except Exception:
            LOG.exception("Не удалось установить глобальные клавиши")
            if self._tray is not None:
                self._tray.showMessage(
                    "БТ-7274",
                    "Глобальная клавиша F1 недоступна. Запустите main.py от администратора.",
                    QSystemTrayIcon.MessageIcon.Critical,
                    8000,
                )

    def _emit_f1_press(self) -> None:
        if not self._closing:
            self._signals.f1_pressed.emit()

    def _emit_f1_release(self) -> None:
        if not self._closing:
            self._signals.f1_released.emit()

    def _setup_tray(self) -> None:
        icon = self._build_tray_icon()
        self._application.setWindowIcon(icon)
        self._overlay.setWindowIcon(icon)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            LOG.warning("Системный трей недоступен")
            return
        self._tray_menu = QMenu()
        self._listen_action = QAction("Слушать (F1)", self._tray_menu)
        self._listen_action.triggered.connect(self._toggle_listen)
        folder_action = QAction("Открыть папку проекта", self._tray_menu)
        folder_action.triggered.connect(self._open_project_folder)
        log_action = QAction("Открыть журнал", self._tray_menu)
        log_action.triggered.connect(self._open_log)
        quit_action = QAction("Завершить БТ-7274", self._tray_menu)
        quit_action.triggered.connect(self._signals.quit_requested.emit)
        self._tray_menu.addAction(self._listen_action)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction(folder_action)
        self._tray_menu.addAction(log_action)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction(quit_action)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("БТ-7274 | F1 — канал пилота | Ctrl+Shift+Q — выход")
        self._tray.setContextMenu(self._tray_menu)
        self._tray.show()

    def _toggle_listen(self) -> None:
        if self._closing:
            return
        if self._state == AgentState.IDLE:
            self._on_f1_pressed()
        elif self._state == AgentState.LISTENING and self._recording:
            self._on_f1_released()

    def _refresh_tray_listen_action(self) -> None:
        if self._listen_action is None:
            return
        if self._state == AgentState.LISTENING and self._recording:
            self._listen_action.setText("Остановить запись")
            self._listen_action.setEnabled(True)
        elif self._state == AgentState.IDLE:
            self._listen_action.setText("Слушать (F1)")
            self._listen_action.setEnabled(True)
        else:
            self._listen_action.setText("Канал занят...")
            self._listen_action.setEnabled(False)

    @staticmethod
    def _open_project_folder() -> None:
        try:
            os.startfile(str(BASE_DIR))
        except Exception:
            LOG.exception("Не удалось открыть папку проекта")

    @staticmethod
    def _open_log() -> None:
        try:
            if LOG_PATH.exists():
                os.startfile(str(LOG_PATH))
            else:
                os.startfile(str(BASE_DIR))
        except Exception:
            LOG.exception("Не удалось открыть журнал")

    @staticmethod
    def _build_tray_icon() -> QIcon:
        pixmap = QPixmap(str(HELMET_PATH)) if HELMET_PATH.exists() else QPixmap()
        canvas = QPixmap(64, 64)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if not pixmap.isNull():
            side = min(pixmap.width(), pixmap.height())
            crop = pixmap.copy(
                (pixmap.width() - side) // 2,
                (pixmap.height() - side) // 2,
                side,
                side,
            )
            clip_path = QPainterPath()
            clip_path.addRoundedRect(QRectF(1.0, 1.0, 62.0, 62.0), 10.0, 10.0)
            painter.save()
            painter.setClipPath(clip_path)
            painter.drawPixmap(0, 0, 64, 64, crop)
            painter.restore()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 232, 255, 220), 2))
            painter.drawRoundedRect(QRectF(1.0, 1.0, 62.0, 62.0), 10.0, 10.0)
        else:
            painter.setPen(QPen(QColor(0, 232, 255), 2))
            painter.setBrush(QColor(1, 18, 27))
            painter.drawEllipse(4, 4, 56, 56)
            painter.setBrush(QColor(0, 190, 230, 100))
            painter.drawRoundedRect(16, 22, 32, 18, 8, 8)
            painter.setPen(QPen(QColor(180, 252, 255), 2))
            painter.drawLine(20, 46, 44, 46)
        painter.end()
        return QIcon(canvas)

    def _on_f1_pressed(self) -> None:
        if self._closing or self._state != AgentState.IDLE:
            return
        self._overlay_hide_timer.stop()
        self._brain.ensure_loaded_async()
        self._state = AgentState.LISTENING
        LOG.info("Состояние: LISTENING")
        self._overlay.show_listening("КАНАЛ ОТКРЫТ. ГОВОРИТЕ, ПИЛОТ.")
        self._refresh_tray_listen_action()
        try:
            self._recorder.start()
            self._recording = True
            self._record_timeout.start(MAX_RECORD_SECONDS * 1000)
            self._refresh_tray_listen_action()
        except Exception as error:
            LOG.exception("Микрофон не открылся")
            self._recording = False
            self._record_timeout.stop()
            message = str(error) if error else "Микрофон недоступен."
            self._overlay.set_status(message.upper())
            QTimer.singleShot(2800, self._abort_listening)

    def _abort_listening(self) -> None:
        if self._closing:
            return
        if self._state == AgentState.LISTENING and not self._recording:
            self._state = AgentState.IDLE
            if not self._visual_recording:
                self._overlay.finish_and_hide()
            self._refresh_tray_listen_action()
            LOG.info("Состояние: IDLE после ошибки микрофона")

    def _on_f1_released(self) -> None:
        if self._closing or not self._recording:
            return
        self._record_timeout.stop()
        self._recording = False
        self._state = AgentState.THINKING
        LOG.info("Состояние: THINKING")
        self._overlay.set_status("ДЕШИФРУЮ ПРИКАЗ...")
        self._refresh_tray_listen_action()
        try:
            audio, sample_rate = self._recorder.stop()
        except Exception as error:
            LOG.exception("Ошибка остановки записи")
            self._overlay.set_status("СБОЙ АУДИОКАНАЛА.")
            QTimer.singleShot(2600, self._finish_failed_session)
            return
        if audio.size == 0:
            self._overlay.set_status("АУДИОКАНАЛ ПУСТ. ПОВТОРИТЕ, ПИЛОТ.")
            QTimer.singleShot(2600, self._finish_failed_session)
            return
        thread = threading.Thread(
            target=self._process_command,
            args=(audio, sample_rate),
            name="bt-brain",
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            LOG.exception("Не удалось запустить поток обработки приказа")
            self._overlay.set_status("СБОЙ ЗАПУСКА ДАТА-ЯДРА.")
            QTimer.singleShot(2600, self._finish_failed_session)

    def _finish_failed_session(self) -> None:
        if self._closing:
            return
        self._overlay_hide_timer.stop()
        self._state = AgentState.IDLE
        self._refresh_tray_listen_action()
        if not self._visual_recording:
            self._overlay.finish_and_hide()
        LOG.info("Состояние: IDLE после сбоя")

    def _on_record_timeout(self) -> None:
        if self._recording:
            LOG.warning("Достигнут лимит записи %s секунд", MAX_RECORD_SECONDS)
            self._on_f1_released()

    def _process_command(self, audio: np.ndarray, sample_rate: int) -> None:
        try:
            prepared = prepare_audio(audio, sample_rate)
            if not self._whisper.ready:
                self._signals.status.emit("ЗАГРУЖАЮ НЕЙРОЯДРО WHISPER...")
            recognized = self._whisper.transcribe(prepared)
            command = strip_wake_name(recognized)
            LOG.info("Приказ после очистки позывного: %s", command)
            if not command:
                raise SpeechRecognitionError(
                    "Позывной принят, но приказ не распознан. Повторите, пилот."
                )
            append_chat_history("ПИЛОТ", command)
            fixed_response = match_fixed_dialogue(command)
            if fixed_response:
                LOG.info("Быстрый диалоговый ответ: %s", fixed_response)
                self._signals.subtitle.emit(fixed_response)
                self._speak_response(fixed_response)
                return
            if self._handle_local_command(command):
                return
            hinted_action = infer_action_from_command(command)
            if hinted_action in RECORD_TAGS:
                response = self._run_recording_tag(hinted_action)
                LOG.info("Запись OBS: действие=%s, ответ=%s", hinted_action, response)
                self._signals.subtitle.emit(response)
                self._speak_response(response)
                return
            if hinted_action:
                response = build_action_response(hinted_action, command)
                LOG.info(
                    "Быстрый локальный маршрут: действие=%s, ответ=%s",
                    hinted_action,
                    response,
                )
                self._signals.subtitle.emit(response)
                try:
                    self._actions.submit([hinted_action], command)
                except Exception:
                    LOG.exception("Не удалось запустить исполнитель действий")
                self._speak_response(response)
                return
            self._signals.status.emit("ЗАПРОС К ДАТА-ЯДРУ...")
            raw_response = self._brain.ask(command)
            tags, response = parse_model_output(raw_response)
            LOG.info("Сырой ответ Ollama: %s", raw_response)
            LOG.info("Теги: %s | Ответ: %s", tags, response)
            model_actions = [tag for tag in tags if tag in ACTION_TAGS]
            if model_actions:
                # Действия выполняются только по явной локальной команде.
                # Маленькая модель иногда добавляет тег к свободному ответу,
                # и его выполнение может свернуть окна или запустить запись.
                LOG.warning(
                    "Действия из ответа Ollama отклонены: %s. "
                    "Для действия нужна явная команда пилота.",
                    model_actions,
                )
            if not response:
                raise BrainError("Дата-ядро не сформировало ответ.")
            self._signals.subtitle.emit(response)
            self._speak_response(response)
        except UserFacingError as error:
            LOG.warning("Прикладная ошибка: %s", error)
            self._show_error(str(error))
        except Exception:
            LOG.exception("Необработанный сбой конвейера")
            self._show_error("Сбой протокола. Проверьте журнал bt7274.log.")
        finally:
            self._signals.session_finished.emit()

    def _emit_response(self, subtitle: str, speech: str | None = None) -> None:
        """Показывает подробный текст и озвучивает короткую версию."""
        self._signals.subtitle.emit(subtitle)
        self._speak_response(speech if speech is not None else subtitle)

    def _handle_local_command(self, command: str) -> bool:
        """Мгновенные команды без обращения к Ollama."""
        text = re.sub(r"\s+", " ", command or "").strip()
        lowered = text.lower()

        if LOCAL_REPEAT_RE.match(lowered):
            if not self._last_response:
                self._emit_response("Нечего повторять, пилот.")
                return True
            LOG.info("Локально: повтор ответа")
            self._signals.subtitle.emit(self._last_response)
            self._speak_response(self._last_response)
            return True

        if LOCAL_CANCEL_RE.match(lowered):
            LOG.info("Локально: отмена речи")
            try:
                sd.stop()
            except Exception:
                pass
            self._last_response = "Приказ отменён, пилот."
            self._last_voice_ok = True
            self._signals.subtitle.emit(self._last_response)
            return True

        if LOCAL_UNLOAD_RE.match(lowered):
            LOG.info("Локально: выгрузка Ollama")
            if not self._brain.model_loaded():
                self._emit_response("Дата-ядро уже выгружено, пилот.")
                return True
            if self._brain.unload():
                self._emit_response("Дата-ядро выгружено из памяти, пилот.")
            else:
                self._emit_response("Не удалось выгрузить дата-ядро, пилот.")
            return True

        if LOCAL_TIME_RE.search(lowered):
            LOG.info("Локально: время")
            self._emit_response(build_time_response())
            return True

        if LOCAL_DATE_RE.search(lowered):
            LOG.info("Локально: дата")
            self._emit_response(build_date_response())
            return True

        diagnostic_kind = diagnostic_kind_from_command(text)
        if diagnostic_kind is not None:
            LOG.info("Локально: диагностика (%s)", diagnostic_kind or "полная")
            self._signals.status.emit("СЧИТЫВАЮ ТЕЛЕМЕТРИЮ...")
            try:
                detail, speech = build_system_report(diagnostic_kind)
            except Exception:
                LOG.exception("Диагностика не удалась")
                self._emit_response("Телеметрия недоступна, пилот.")
                return True
            self._emit_response(detail, speech)
            return True

        clipboard_write = LOCAL_CLIPBOARD_WRITE_RE.match(text)
        if clipboard_write:
            value = (clipboard_write.group("text") or "").strip(" .,!?:;-—\"«»")
            if value:
                try:
                    pyperclip.copy(value)
                except Exception:
                    LOG.exception("Буфер обмена недоступен для записи")
                    self._emit_response("Буфер обмена недоступен, пилот.")
                    return True
                LOG.info("Локально: скопировано %s символов", len(value))
                self._emit_response("Скопировано в буфер обмена, пилот.")
                return True

        if LOCAL_CLIPBOARD_READ_RE.search(lowered):
            try:
                value = (pyperclip.paste() or "").strip()
            except Exception:
                LOG.exception("Буфер обмена недоступен для чтения")
                self._emit_response("Буфер обмена недоступен, пилот.")
                return True
            if not value:
                self._emit_response("Буфер обмена пуст, пилот.")
                return True
            clipped = value if len(value) <= 280 else value[:280] + "…"
            chars = plural_ru(len(value), "символ", "символа", "символов")
            self._emit_response(
                f"Буфер обмена:\n{clipped}",
                f"В буфере обмена {len(value)} {chars}, пилот.",
            )
            return True

        note_write = LOCAL_NOTE_WRITE_RE.match(text)
        if note_write:
            value = (note_write.group("text") or note_write.group("text_two") or "")
            value = value.strip(" .,!?:;-—\"«»")
            if value:
                try:
                    append_note(value)
                except Exception:
                    LOG.exception("Не удалось сохранить заметку")
                    self._emit_response("Хранилище заметок недоступно, пилот.")
                    return True
                LOG.info("Локально: заметка сохранена")
                self._emit_response("Заметка сохранена, пилот.")
                return True

        if LOCAL_NOTE_READ_RE.search(lowered):
            notes = read_notes(4)
            if not notes:
                self._emit_response("Заметки пусты, пилот.")
                return True
            display_notes = [
                note if len(note) <= 70 else note[:67] + "…" for note in notes
            ]
            count = plural_ru(len(notes), "запись", "записи", "записей")
            self._emit_response(
                "Заметки:\n" + "\n".join(display_notes),
                f"На дисплее {len(notes)} {count}, пилот.",
            )
            return True

        timer = parse_timer_command(text)
        if timer is not None:
            seconds, label, reminder = timer
            LOG.info("Локально: таймер на %s секунд", seconds)
            self._signals.timer_requested.emit(seconds, label, reminder)
            response = f"Таймер на {label} установлен, пилот."
            if reminder:
                response += f" Напоминание: {reminder}."
            self._emit_response(response)
            return True

        if LOCAL_LAST_SHOT_RE.search(lowered):
            path = latest_media_in_archive(
                (SHOTS_DIR, BASE_DIR),
                SCREENSHOT_PREFIXES,
                (".png", ".jpg", ".jpeg", ".webp"),
            )
            if path is None:
                self._emit_response("В архиве нет снимков, пилот.")
                return True
            try:
                os.startfile(str(path))
            except OSError:
                LOG.exception("Не удалось открыть скриншот")
                self._emit_response("Не удалось открыть снимок, пилот.")
                return True
            self._emit_response("Последний снимок открыт, пилот.")
            return True

        if LOCAL_LAST_CLIP_RE.search(lowered):
            path = latest_media_in_archive(
                (CLIPS_DIR, BASE_DIR),
                VIDEO_PREFIXES,
                (".mp4", ".mkv", ".mov", ".avi", ".flv"),
            )
            if path is None:
                self._emit_response("В архиве нет клипов, пилот.")
                return True
            try:
                os.startfile(str(path))
            except OSError:
                LOG.exception("Не удалось открыть клип")
                self._emit_response("Не удалось открыть клип, пилот.")
                return True
            self._emit_response("Последний клип открыт, пилот.")
            return True

        hinted_action = infer_action_from_command(text)
        if hinted_action in {"OBS_PAUSE", "OBS_RESUME", "OBS_NEXT_SCENE"}:
            LOG.info("Локально: OBS %s", hinted_action)
            self._signals.status.emit("УПРАВЛЯЮ OBS...")
            try:
                response = self._actions.run_now(hinted_action, text)
            except Exception as error:
                LOG.exception("Сбой управления OBS")
                response = f"ОШИБКА OBS: {error}"
            self._emit_response(response)
            return True

        return False

    def _run_recording_tag(self, tag: str) -> str:
        if tag == "RECORD_VIDEO_START":
            if self._visual_recording:
                return "Запись уже идёт, пилот. Ожидаю команду стоп."
            self._signals.status.emit("УСТАНАВЛИВАЮ СВЯЗЬ С OBS...")
            try:
                result = self._actions.run_now(tag)
            except Exception as error:
                LOG.exception("Не удалось запустить запись OBS")
                return f"ОШИБКА ЗАПУСКА ЗАПИСИ: {error}"
            self._visual_recording = True
            LOG.info("Визуальная запись запущена: %s", result)
            return DEFAULT_ACTION_RESPONSES["RECORD_VIDEO_START"]
        if tag == "RECORD_VIDEO_STOP":
            if not self._visual_recording:
                return "Запись не активна, пилот."
            self._signals.status.emit("ОСТАНАВЛИВАЮ ЗАПИСЬ...")
            try:
                result = self._actions.run_now(tag)
            except Exception as error:
                LOG.exception("Не удалось остановить запись OBS")
                return f"ОШИБКА ОСТАНОВКИ ЗАПИСИ: {error}"
            self._visual_recording = False
            LOG.info("Визуальная запись остановлена: %s", result)
            return DEFAULT_ACTION_RESPONSES["RECORD_VIDEO_STOP"]
        return ""

    def _speak_response(self, response: str) -> None:
        self._last_response = response
        append_chat_history("БТ", response)
        try:
            self._voice.speak(response)
            self._last_voice_ok = True
        except Exception:
            LOG.exception("Голосовой канал недоступен, ответ остаётся текстом")
            self._last_voice_ok = False

    def _show_error(self, message: str) -> None:
        self._last_response = message
        self._last_voice_ok = False
        self._signals.subtitle.emit(message)

    def _on_status(self, text: str) -> None:
        if self._closing:
            return
        if self._overlay.isVisible():
            self._overlay.set_status(text)

    def _on_subtitle(self, text: str) -> None:
        if self._closing:
            return
        if self._state == AgentState.THINKING:
            self._state = AgentState.SPEAKING
            LOG.info("Состояние: SPEAKING")
            self._refresh_tray_listen_action()
        self._overlay.show_response(text)

    def _on_action_done(self, tag: str, result: str) -> None:
        LOG.info("Результат действия %s: %s", tag, result)
        if result.startswith("ОШИБКА") and self._tray is not None:
            self._tray.showMessage(
                "БТ-7274: сбой действия",
                f"{tag}: {result}",
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )

    def _on_session_finished(self) -> None:
        if self._closing:
            return
        self._recording = False
        self._record_timeout.stop()
        self._state = AgentState.IDLE
        self._refresh_tray_listen_action()
        if self._visual_recording:
            LOG.info("Состояние: IDLE, оверлей остаётся: идёт запись OBS")
            return
        if self._last_voice_ok:
            delay = 1200
        else:
            delay = min(7000, max(2200, int(len(self._last_response) / 18.0 * 1000)))
        self._overlay_hide_timer.start(delay)
        LOG.info("Состояние: IDLE, оверлей скроется через %s мс", delay)

    def _hide_overlay_if_idle(self) -> None:
        if self._closing or self._visual_recording or self._recording:
            return
        if self._state != AgentState.IDLE:
            return
        self._overlay.finish_and_hide()
        LOG.info("Оверлей скрыт")

    def _on_timer_requested(self, seconds: int, label: str, reminder: str) -> None:
        if self._closing:
            return
        delay = max(1, int(seconds)) * 1000
        LOG.info("Таймер установлен: %s мс, напоминание=%s", delay, reminder or "нет")
        QTimer.singleShot(delay, lambda: self._on_timer_fired(label, reminder))

    def _on_timer_fired(self, label: str, reminder: str) -> None:
        if self._closing:
            return
        message = f"Время вышло, пилот. Таймер на {label} завершён."
        if reminder:
            message += f" Напоминание: {reminder}."
        LOG.info("Таймер сработал: %s", message)
        if self._state != AgentState.IDLE:
            self._signals.subtitle.emit(message)
            LOG.info("Таймер: голосовой канал занят, уведомление только текстом")
            return
        self._state = AgentState.SPEAKING
        self._refresh_tray_listen_action()
        self._signals.subtitle.emit(message)

        def announce() -> None:
            try:
                self._speak_response(message)
            finally:
                self._signals.session_finished.emit()

        threading.Thread(
            target=announce,
            name="bt-timer",
            daemon=True,
        ).start()

    def request_quit(self) -> None:
        if self._closing:
            return
        LOG.info("Получен приказ на завершение")
        self.shutdown()
        self._application.quit()

    def _poll_shutdown_request(self) -> None:
        """Штатное завершение по флагу командного центра launcher.py."""
        if self._closing or not SHUTDOWN_REQUEST_PATH.exists():
            return
        try:
            SHUTDOWN_REQUEST_PATH.unlink()
        except OSError:
            LOG.warning("Не удалось удалить флаг завершения, продолжаю выход")
        LOG.info("Получен запрос на штатное завершение от командного центра")
        self.request_quit()

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._shutdown_timer.stop()
        if self._visual_recording:
            try:
                result = self._actions.stop_obs_recording(finalize_timeout=4.0)
                LOG.info("Запись OBS остановлена при выключении БТ: %s", result)
            except Exception:
                LOG.exception("Не удалось остановить запись OBS при выключении")
            self._visual_recording = False
        self._record_timeout.stop()
        self._overlay_hide_timer.stop()
        self._recording = False
        try:
            self._recorder.cancel()
        except Exception:
            LOG.exception("Ошибка закрытия микрофона")
        for remover in self._hotkey_removers:
            try:
                remover()
            except Exception:
                pass
        self._hotkey_removers.clear()
        try:
            sd.stop()
        except Exception:
            pass
        try:
            self._brain.stop_warmup()
            self._brain.unload()
        except Exception:
            LOG.exception("Не удалось выгрузить Ollama при выключении")
        if self._tray is not None:
            self._tray.hide()
        self._overlay.finish_and_hide()
        append_chat_history("СИСТЕМА", "Нейролинк БТ-7274 отключён.")
        LOG.info("БТ-7274 выключен")


def install_exception_hook() -> None:
    def handle_exception(
        exception_type: type[BaseException],
        exception_value: BaseException,
        traceback_object: Any,
    ) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception_value, traceback_object)
            return
        LOG.critical(
            "Необработанное исключение",
            exc_info=(exception_type, exception_value, traceback_object),
        )

    sys.excepthook = handle_exception


def main() -> int:
    LOG.info("Старт БТ-7274 %s", APP_VERSION)
    install_exception_hook()
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName("BT-7274")
    application.setQuitOnLastWindowClosed(False)
    instance_lock = QLockFile(str(INSTANCE_LOCK_PATH))
    instance_lock.setStaleLockTime(30000)
    if not instance_lock.tryLock(200):
        LOG.warning("Повторный запуск отклонён: экземпляр уже работает")
        QMessageBox.warning(
            None,
            APP_NAME,
            "БТ-7274 уже запущен.\n\n"
            "Управление: F1 — канал пилота, Ctrl+Shift+Q — выход.\n"
            "Иконка титана находится в системном трее.",
        )
        return 0
    try:
        controller = BT7274Controller(application)
        application.aboutToQuit.connect(controller.shutdown)
        controller.start()
        return application.exec()
    finally:
        instance_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
