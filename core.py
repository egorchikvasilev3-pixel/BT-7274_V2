"""
core.py — логика командного центра без интерфейса: процессы, Ollama, журнал чата, файлы архива.
"""

import glob
import os
import re
import subprocess
import sys
from datetime import datetime

import psutil
import requests

from config import (
    BASE_DIR,
    CHAT_HISTORY_FILE,
    CLIPS_DIR,
    CREATE_NO_WINDOW,
    LOCK_FILE,
    OLLAMA_MODEL,
    OLLAMA_TAGS_URL,
    SCREENSHOT_PREFIXES,
    SHOTS_DIR,
    VIDEO_PREFIXES,
)

CHAT_LINE_PATTERN = re.compile(r"^\[(?P<time>[^\]]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$")


def resolve_python_gui():
    """Возвращает путь к pythonw.exe для запуска main.py без консоли."""
    if getattr(sys, "frozen", False):
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return "pythonw"
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.isfile(pythonw):
        return pythonw
    return sys.executable


def read_lock_pid():
    """Читает PID из lock-файла БТ-7274. Возвращает None, если файла нет или он испорчен."""
    try:
        with open(LOCK_FILE, "r", encoding="utf-8", errors="ignore") as lock:
            first_line = lock.readline().strip()
    except OSError:
        return None
    return int(first_line) if first_line.isdigit() else None


def is_python_process(pid):
    """Проверяет, что процесс с этим PID существует и это Python."""
    if not pid:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "python" in result.stdout.lower()


def is_bt_process(pid):
    """Проверяет PID БТ и в исходном режиме, и во встроенном режиме exe."""
    if is_python_process(pid):
        return True
    if not pid:
        return False
    try:
        process = psutil.Process(int(pid))
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        name = str(process.name() or "").lower()
        if not name.startswith("bt-7274_command"):
            return False
        try:
            command_line = " ".join(process.cmdline()).lower()
        except (psutil.Error, OSError):
            return True
        return "--agent" in command_line or "main.py" in command_line
    except (psutil.Error, OSError, ValueError):
        return False


def terminate_bt_by_lock():
    """Завершает процесс БТ по PID из lock-файла, если он жив."""
    pid = read_lock_pid()
    if is_bt_process(pid):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )


def check_ollama():
    """
    Синхронный запрос к Ollama. Возвращает кортеж (доступна, модель_найдена).
    Вызывать из фонового потока.
    """
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=2)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return False, False
    names = [str(item.get("name", "")) for item in payload.get("models", [])]
    found = any(name == OLLAMA_MODEL or name.startswith(OLLAMA_MODEL) for name in names)
    return True, found


def _process_running(prefixes):
    """Проверяет, запущен ли процесс по началу имени (без внешних вызовов)."""
    try:
        for process in psutil.process_iter(["name"]):
            name = str(process.info.get("name") or "").lower()
            if any(name.startswith(prefix) for prefix in prefixes):
                return True
    except (psutil.Error, OSError):
        return False
    return False


def read_gpu_telemetry():
    """Читает загрузку и температуру NVIDIA GPU; возвращает пустой словарь при сбое."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return {}
        first_line = result.stdout.strip().splitlines()[0]
        parts = [part.strip() for part in first_line.split(",")]
        return {
            "gpu_util": float(parts[0]),
            "gpu_temp": float(parts[1]),
        }
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {}


def collect_telemetry(include_gpu=True):
    """Собирает лёгкую телеметрию для нижней панели лаунчера."""
    try:
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        data = {
            "cpu": cpu,
            "ram_used": memory.used / (1024**3),
            "ram_total": memory.total / (1024**3),
            "ollama": _process_running(("ollama",)),
            "obs": _process_running(("obs64", "obs32")),
        }
    except (psutil.Error, OSError):
        return {}
    if include_gpu:
        data.update(read_gpu_telemetry())
    return data


def ensure_chat_history():
    """Создаёт chat_history.txt с заголовком, если файла ещё нет. Возвращает путь к нему."""
    if not os.path.isfile(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as history:
            history.write("# Журнал синхронизации БТ-7274\n")
    return CHAT_HISTORY_FILE


def append_chat_line(speaker, text):
    """Дописывает строку в журнал в формате [ВРЕМЯ] Говорящий: текст."""
    ensure_chat_history()
    stamp = datetime.now().strftime("%H:%M:%S")
    clean_text = " ".join(str(text).split())
    with open(CHAT_HISTORY_FILE, "a", encoding="utf-8") as history:
        history.write(f"[{stamp}] {speaker}: {clean_text}\n")


def read_chat_entries():
    """
    Читает журнал и возвращает список кортежей (время, говорящий, текст).
    Строки, не подходящие под формат, пропускаются.
    """
    ensure_chat_history()
    entries = []
    with open(CHAT_HISTORY_FILE, "r", encoding="utf-8", errors="ignore") as history:
        for raw_line in history:
            match = CHAT_LINE_PATTERN.match(raw_line.strip())
            if match:
                entries.append((match.group("time"), match.group("speaker").strip(), match.group("text")))
    return entries


def _matching_files(prefixes, extension):
    """
    Ищет файлы по префиксам и расширению в корне проекта и архивных папках,
    новые сверху. Корень оставлен для старых файлов предыдущих версий.
    """
    found = []
    seen = set()
    for directory in (BASE_DIR, SHOTS_DIR, CLIPS_DIR):
        if not os.path.isdir(directory):
            continue
        for path in glob.glob(os.path.join(directory, f"*{extension}")):
            name = os.path.basename(path)
            normalized = os.path.normcase(os.path.abspath(path))
            if name.startswith(prefixes) and normalized not in seen:
                found.append(path)
                seen.add(normalized)
    return sorted(found, key=os.path.getmtime, reverse=True)


def list_screenshots():
    """Скриншоты screenshot_*.png и bt_screenshot_*.png из shots и корня."""
    return _matching_files(SCREENSHOT_PREFIXES, ".png")


def list_videos():
    """Видео clip_*.mp4 и bt_highlight_*.mp4 из clips и корня."""
    return _matching_files(VIDEO_PREFIXES, ".mp4")


def format_mtime(path):
    """Дата и время создания файла в читаемом виде."""
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d.%m.%Y %H:%M:%S")


def open_with_default_app(path):
    """Открывает файл стандартным приложением Windows."""
    os.startfile(path)
