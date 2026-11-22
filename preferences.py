"""
preferences.py — настройки пилота: браузер, музыкальный сервис и поисковик.

Модуль не зависит от PySide6: его используют и лаунчер, и голосовой агент.
Настройки хранятся в data/settings.json рядом с программой.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

SETTINGS_RELATIVE_PATH = Path("data") / "settings.json"

DEFAULT_SETTINGS = {
    "browser": "default",
    "music_service": "youtube_music",
    "search_engine": "google",
}

BROWSER_LABELS = {
    "default": "Браузер по умолчанию",
    "firefox": "Mozilla Firefox",
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "opera": "Opera",
    "opera_gx": "Opera GX",
    "brave": "Brave",
    "vivaldi": "Vivaldi",
    "yandex": "Яндекс Браузер",
}
BROWSER_ORDER = (
    "firefox",
    "chrome",
    "edge",
    "opera",
    "opera_gx",
    "brave",
    "vivaldi",
    "yandex",
)

MUSIC_SERVICE_LABELS = {
    "youtube_music": "YouTube Music",
    "vk_music": "VK Music",
    "yandex_music": "Яндекс Музыка",
    "spotify": "Spotify",
    "soundcloud": "SoundCloud",
}

SEARCH_ENGINE_LABELS = {
    "google": "Google",
    "yandex": "Яндекс",
}

# Формы для озвучки: Edge TTS плохо читает латиницу, поэтому голосу
# передаются русские названия, а в интерфейсе остаются фирменные.
MUSIC_SERVICE_SPEECH_LABELS = {
    "youtube_music": "Ютуб Мьюзик",
    "vk_music": "Вэка Мьюзик",
    "yandex_music": "Яндекс Музыку",
    "spotify": "Спотифай",
    "soundcloud": "Саундклауд",
}

BROWSER_SPEECH_LABELS = {
    "default": "браузер по умолчанию",
    "firefox": "Файрфокс",
    "chrome": "Хром",
    "edge": "Эдж",
    "opera": "Оперу",
    "opera_gx": "Оперу Джи Экс",
    "brave": "Брейв",
    "vivaldi": "Вивальди",
    "yandex": "Яндекс Браузер",
}

SEARCH_ENGINE_SPEECH_IN = {
    "google": "Гугле",
    "yandex": "Яндексе",
}

MUSIC_HOME_URLS = {
    "youtube_music": "https://music.youtube.com",
    "vk_music": "https://vk.com/music",
    "yandex_music": "https://music.yandex.ru",
    "spotify": "https://open.spotify.com",
    "soundcloud": "https://soundcloud.com",
}

MUSIC_SEARCH_URLS = {
    "youtube_music": "https://music.youtube.com/search?q={query}",
    "vk_music": "https://vk.com/search/audio?c%5Bq%5D={query}",
    "yandex_music": "https://music.yandex.ru/search?text={query}",
    "spotify": "https://open.spotify.com/search/{query}",
    "soundcloud": "https://soundcloud.com/search?q={query}",
}

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={query}",
    "yandex": "https://yandex.ru/search/?text={query}",
}

YOUTUBE_HOME_URL = "https://www.youtube.com"
YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={query}"

_BROWSER_RELATIVE_PATHS = {
    "firefox": (r"Mozilla Firefox\firefox.exe",),
    "chrome": (r"Google\Chrome\Application\chrome.exe",),
    "edge": (r"Microsoft\Edge\Application\msedge.exe",),
    "opera": (
        r"Opera\opera.exe",
        r"Programs\Opera\opera.exe",
        r"Opera\launcher.exe",
        r"Programs\Opera\launcher.exe",
    ),
    "opera_gx": (
        r"Opera GX\opera.exe",
        r"Programs\Opera GX\opera.exe",
        r"Opera GX\launcher.exe",
        r"Programs\Opera GX\launcher.exe",
    ),
    "brave": (r"BraveSoftware\Brave-Browser\Application\brave.exe",),
    "vivaldi": (r"Vivaldi\Application\vivaldi.exe",),
    "yandex": (r"Yandex\YandexBrowser\Application\browser.exe",),
}

_POLITE_RE = re.compile(r"\b(?:пожалуйста|плиз|будь\s+добр\w*)\b", re.IGNORECASE)
_LEADING_COMMAND_RE = re.compile(
    r"^\s*(?:(?:бт|bt)[\s-]*7274[\s,.:;-]*)?"
    r"(?:(?:включи|включай|вруби|запусти|запускай|открой|открывай|поставь|"
    r"найди|поищи|поиск|загугли|погугли|ищи)\s+)+",
    re.IGNORECASE,
)
_SERVICE_STRIP_RE = re.compile(
    r"\b(?:youtube\s*music|youtube\s*музык\w*|ютуб\s*мьюзик|ютуб\s*музык\w*|"
    r"вэка\s*мьюзик\w*|вэка\s*музык\w*|вэ\s*ка\s*мьюзик\w*|"
    r"вэ\s*ка\s*музык\w*|вк\s*музык\w*|vk\s*music|вконтакте|вк|vk|"
    r"яндекс\s*музык\w*|yandex\s*music|яндекс\w*|yandex\w*|"
    r"spotify|спотифай|soundcloud|саундклауд|youtube\w*|ютуб\w*)\b",
    re.IGNORECASE,
)
_BROWSER_STRIP_RE = re.compile(
    r"\b(?:opera\s*gx|опера\s*gx|firefox|файрфокс\w*|фаерфокс\w*|мозилл\w*|"
    r"chrome|хром\w*|гугл\s*хром\w*|edge|эдж\w*|мс\s*эдж\w*|"
    r"opera|опер(?:а|ы|е|у|ой|ою)\b|brave|брейв\w*|vivaldi|вивальди|"
    r"яндекс\s*браузер\w*|yandex\s*browser|браузер\w*)\b",
    re.IGNORECASE,
)
_MUSIC_WORD_RE = re.compile(
    r"\b(?:музык\w*|песн\w*|трек\w*|композиц\w*|плейлист\w*|альбом\w*|"
    r"исполнител\w*|радио|канал)\b",
    re.IGNORECASE,
)
_VIDEO_WORD_RE = re.compile(
    r"\b(?:видео|клип\w*|ролик\w*|фильм\w*|трейлер\w*|мультфильм\w*)\b",
    re.IGNORECASE,
)
_VIDEO_INTENT_RE = re.compile(
    r"\b(?:видео|клип\w*|ролик\w*|фильм\w*|трейлер\w*|мультфильм\w*)\b",
    re.IGNORECASE,
)
_BROWSER_TEXT_PATTERNS = (
    (
        "opera_gx",
        re.compile(r"\b(?:opera\s*gx|опера\s*gx)\b", re.IGNORECASE),
    ),
    (
        "firefox",
        re.compile(
            r"\b(?:firefox|файрфокс\w*|фаерфокс\w*|мозилл\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "chrome",
        re.compile(r"\b(?:chrome|хром\w*|гугл\s*хром\w*)\b", re.IGNORECASE),
    ),
    (
        "edge",
        re.compile(r"\b(?:edge|эдж\w*|мс\s*эдж\w*)\b", re.IGNORECASE),
    ),
    (
        "opera",
        re.compile(
            r"\b(?:opera|опер(?:а|ы|е|у|ой|ою))\b",
            re.IGNORECASE,
        ),
    ),
    ("brave", re.compile(r"\b(?:brave|брейв\w*)\b", re.IGNORECASE)),
    ("vivaldi", re.compile(r"\b(?:vivaldi|вивальди)\b", re.IGNORECASE)),
    (
        "yandex",
        re.compile(
            r"\b(?:яндекс\s*браузер\w*|yandex\s*browser)\b",
            re.IGNORECASE,
        ),
    ),
)
_MUSIC_SERVICE_PATTERNS = (
    (
        "youtube_music",
        re.compile(
            r"\b(?:youtube\s*music|youtube\s*музык\w*|ютуб\s*мьюзик|"
            r"ютуб\s*музык\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "vk_music",
        re.compile(
            r"\b(?:вэка\s*мьюзик\w*|вэка\s*музык\w*|вэ\s*ка\s*мьюзик\w*|"
            r"вэ\s*ка\s*музык\w*|вк\s*музык\w*|vk\s*music|вконтакте|вк|vk)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "yandex_music",
        re.compile(
            r"\b(?:яндекс\s*музык\w*|yandex\s*music|яндекс\w*|yandex\w*)\b",
            re.IGNORECASE,
        ),
    ),
    ("spotify", re.compile(r"\b(?:spotify|спотифай)\b", re.IGNORECASE)),
    (
        "soundcloud",
        re.compile(r"\b(?:soundcloud|саундклауд)\b", re.IGNORECASE),
    ),
    ("youtube_music", re.compile(r"\b(?:youtube|ютуб)\b", re.IGNORECASE)),
)


def _program_roots() -> list[str]:
    """Каталоги, где обычно лежат установленные браузеры."""
    roots = []
    for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        value = os.environ.get(name)
        if value and value not in roots:
            roots.append(value)
    return roots


def _known_browser_candidates(browser_key: str):
    """Перебирает известные пути установки браузера."""
    for root in _program_roots():
        base = Path(root)
        for relative in _BROWSER_RELATIVE_PATHS.get(browser_key, ()):
            yield base / relative


def _extract_executable(command: str) -> str:
    """Достаёт путь к exe из команды реестра."""
    text = str(command or "").strip()
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 1:
            return text[1:end]
    match = re.match(r"^(.*?\.exe)\b", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _browser_key_from_path(path: str) -> str:
    """Определяет браузер по пути к исполняемому файлу."""
    lowered = str(path or "").lower().replace("/", "\\")
    name = os.path.basename(lowered)
    if name == "firefox.exe":
        return "firefox"
    if name == "chrome.exe":
        return "chrome"
    if name == "msedge.exe":
        return "edge"
    if name in {"opera.exe", "launcher.exe"}:
        if "opera gx" in lowered or "operagx" in lowered:
            return "opera_gx"
        if "opera" in lowered:
            return "opera"
        return ""
    if name == "brave.exe":
        return "brave"
    if name == "vivaldi.exe":
        return "vivaldi"
    if name in {"browser.exe", "yandexbrowser.exe"} and "yandex" in lowered:
        return "yandex"
    return ""


def _registry_browser_paths() -> dict[str, str]:
    """Читает пути браузеров из реестра Windows (HKCU/HKLM)."""
    if os.name != "nt":
        return {}
    try:
        import winreg
    except Exception:
        return {}
    roots = (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet",
        ),
    )
    found: dict[str, str] = {}
    for root, subkey in roots:
        try:
            clients = winreg.OpenKey(root, subkey)
        except OSError:
            continue
        with clients:
            index = 0
            while True:
                try:
                    client_name = winreg.EnumKey(clients, index)
                except OSError:
                    break
                index += 1
                try:
                    command_key = winreg.OpenKey(
                        clients, rf"{client_name}\shell\open\command"
                    )
                    with command_key:
                        command = str(winreg.QueryValueEx(command_key, "")[0])
                except OSError:
                    continue
                executable = _extract_executable(command)
                browser_key = _browser_key_from_path(executable)
                if (
                    browser_key
                    and browser_key not in found
                    and executable
                    and Path(executable).is_file()
                ):
                    found[browser_key] = executable
    return found


def detect_browsers() -> dict[str, str]:
    """Возвращает установленные браузеры: ключ -> путь к exe."""
    found = _registry_browser_paths()
    for browser_key in BROWSER_ORDER:
        if browser_key in found:
            continue
        for candidate in _known_browser_candidates(browser_key):
            if candidate.is_file():
                found[browser_key] = str(candidate)
                break
    return found


def _settings_path(base_dir=None) -> Path:
    root = Path(base_dir) if base_dir else BASE_DIR
    return root / SETTINGS_RELATIVE_PATH


def load_settings(base_dir=None) -> dict[str, str]:
    """Читает настройки и подставляет значения по умолчанию."""
    payload = {}
    try:
        with _settings_path(base_dir).open("r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            payload = data
    except (OSError, ValueError):
        payload = {}

    settings = dict(DEFAULT_SETTINGS)
    browser = str(payload.get("browser") or "").strip().lower()
    if browser in BROWSER_LABELS:
        settings["browser"] = browser
    music_service = str(payload.get("music_service") or "").strip().lower()
    if music_service in MUSIC_SERVICE_LABELS:
        settings["music_service"] = music_service
    search_engine = str(payload.get("search_engine") or "").strip().lower()
    if search_engine in SEARCH_ENGINE_LABELS:
        settings["search_engine"] = search_engine
    return settings


def save_settings(settings, base_dir=None) -> Path:
    """Атомарно сохраняет настройки в data/settings.json."""
    payload = dict(DEFAULT_SETTINGS)
    values = settings if isinstance(settings, dict) else {}
    for key, valid in (
        ("browser", BROWSER_LABELS),
        ("music_service", MUSIC_SERVICE_LABELS),
        ("search_engine", SEARCH_ENGINE_LABELS),
    ):
        value = str(values.get(key) or "").strip().lower()
        if value in valid:
            payload[key] = value

    path = _settings_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temporary, path)
    return path


def browser_choices(current=None) -> list[tuple[str, str]]:
    """Список для выпадающего меню: системный браузер и найденные браузеры."""
    installed = detect_browsers()
    choices = [("default", BROWSER_LABELS["default"])]
    for browser_key in BROWSER_ORDER:
        if browser_key in installed:
            choices.append((browser_key, BROWSER_LABELS[browser_key]))
    known = {key for key, _ in choices}
    if current and current not in known:
        choices.append((current, f"{browser_label(current)} (не найден)"))
    return choices


def browser_label(browser_key: str) -> str:
    return BROWSER_LABELS.get(str(browser_key or "default"), BROWSER_LABELS["default"])


def music_service_label(service_key: str) -> str:
    return MUSIC_SERVICE_LABELS.get(
        str(service_key or "youtube_music"),
        MUSIC_SERVICE_LABELS["youtube_music"],
    )


def search_engine_label(engine_key: str) -> str:
    return SEARCH_ENGINE_LABELS.get(
        str(engine_key or "google"),
        SEARCH_ENGINE_LABELS["google"],
    )


def music_service_speech_label(service_key: str) -> str:
    """Название сервиса в форме для озвучки: «Открываю Спотифай»."""
    return MUSIC_SERVICE_SPEECH_LABELS.get(
        str(service_key or "youtube_music"),
        MUSIC_SERVICE_SPEECH_LABELS["youtube_music"],
    )


def browser_speech_label(browser_key: str) -> str:
    """Название браузера в форме для озвучки: «Открываю Оперу»."""
    return BROWSER_SPEECH_LABELS.get(
        str(browser_key or "default"),
        BROWSER_SPEECH_LABELS["default"],
    )


def search_engine_speech_in(engine_key: str) -> str:
    """Поисковик в предложном падеже: «Поиск в Гугле»."""
    return SEARCH_ENGINE_SPEECH_IN.get(
        str(engine_key or "google"),
        SEARCH_ENGINE_SPEECH_IN["google"],
    )


def launch_url(url: str, browser_key=None, base_dir=None) -> tuple[bool, str]:
    """
    Открывает адрес в выбранном браузере.
    Возвращает (успех, предупреждение). Если браузер не найден,
    открывает адрес в браузере по умолчанию и сообщает об этом.
    """
    target = str(url or "").strip()
    if not target:
        return False, "Пустой адрес."
    if browser_key is None:
        browser_key = load_settings(base_dir)["browser"]
    key = str(browser_key or "default").strip().lower()
    if key not in BROWSER_LABELS:
        key = "default"

    if key == "default":
        try:
            if webbrowser.open(target, new=2):
                return True, ""
        except Exception as error:
            return False, f"Не удалось открыть браузер по умолчанию: {error}"
        return False, "Браузер по умолчанию не ответил."

    executable = detect_browsers().get(key)
    if not executable:
        try:
            if webbrowser.open(target, new=2):
                return (
                    True,
                    f"{browser_label(key)} не найден. Открыл в браузере по умолчанию.",
                )
        except Exception as error:
            return False, f"{browser_label(key)} не найден: {error}"
        return False, f"{browser_label(key)} не найден."

    arguments = [executable]
    if key == "firefox":
        arguments.append("-new-tab")
    arguments.append(target)
    try:
        subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True, ""
    except OSError as error:
        message = f"Не удалось запустить {browser_label(key)}: {error}"
        try:
            if webbrowser.open(target, new=2):
                return True, f"{message}. Открыл в браузере по умолчанию."
        except Exception:
            pass
        return False, message


def build_music_url(query: str = "", provider: str = "youtube_music") -> str:
    """URL музыкального сервиса: главная или поиск по запросу."""
    key = str(provider or "").strip().lower()
    if key not in MUSIC_HOME_URLS:
        key = DEFAULT_SETTINGS["music_service"]
    text = str(query or "").strip()
    if not text:
        return MUSIC_HOME_URLS[key]
    return MUSIC_SEARCH_URLS[key].format(query=quote_plus(text))


def build_search_url(query: str, engine: str = "google") -> str:
    """URL поисковика с запросом."""
    key = str(engine or "").strip().lower()
    if key not in SEARCH_URLS:
        key = DEFAULT_SETTINGS["search_engine"]
    return SEARCH_URLS[key].format(query=quote_plus(str(query or "").strip()))


def build_youtube_url(query: str = "") -> str:
    """Главная YouTube или результаты поиска."""
    text = str(query or "").strip()
    if not text:
        return YOUTUBE_HOME_URL
    return YOUTUBE_SEARCH_URL.format(query=quote_plus(text))


def browser_from_text(text: str) -> str | None:
    """Определяет браузер, если пилот назвал его явно."""
    value = str(text or "")
    for browser_key, pattern in _BROWSER_TEXT_PATTERNS:
        if pattern.search(value):
            return browser_key
    return None


def music_service_from_text(text: str) -> str | None:
    """Определяет музыкальный сервис по фразе пилота."""
    value = str(text or "")
    for service_key, pattern in _MUSIC_SERVICE_PATTERNS:
        if pattern.search(value):
            return service_key
    return None


def search_engine_from_text(text: str) -> str | None:
    """Определяет поисковик, если пилот назвал его явно."""
    value = str(text or "")
    if re.search(r"\b(?:яндекс\w*|yandex\w*)\b", value, re.IGNORECASE):
        return "yandex"
    if re.search(
        r"\b(?:гугл\w*|google|загугл\w*|погугл\w*)\b",
        value,
        re.IGNORECASE,
    ):
        return "google"
    return None


def is_video_request(text: str) -> bool:
    """Проверяет, просит ли пилот видео, клип или фильм."""
    return bool(_VIDEO_INTENT_RE.search(str(text or "")))


def _clean_text(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = _POLITE_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" .,!?:;-—\"«»")
    return value


def _strip_query_noise(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^\s*(?:мне|нам|для\s+меня)\s+", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:в|на|из|по|с)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+(?:в|на|из|по|с)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" .,!?:;-—\"«»")
    return value


def clean_music_query(text: str) -> str:
    """Убирает из фразы команду и название сервиса, оставляя запрос."""
    value = _clean_text(text)
    value = _LEADING_COMMAND_RE.sub("", value)
    value = _SERVICE_STRIP_RE.sub(" ", value)
    value = _BROWSER_STRIP_RE.sub(" ", value)
    value = _MUSIC_WORD_RE.sub(" ", value)
    value = _VIDEO_WORD_RE.sub(" ", value)
    value = _strip_query_noise(value)
    return value if len(value) >= 2 else ""


def clean_video_query(text: str) -> str:
    """Убирает из фразы команду и служебные слова для поиска видео."""
    value = _clean_text(text)
    value = _LEADING_COMMAND_RE.sub("", value)
    value = _SERVICE_STRIP_RE.sub(" ", value)
    value = _BROWSER_STRIP_RE.sub(" ", value)
    value = _VIDEO_WORD_RE.sub(" ", value)
    value = _MUSIC_WORD_RE.sub(" ", value)
    value = _strip_query_noise(value)
    return value if len(value) >= 2 else ""


def clean_search_query(text: str) -> str:
    """Убирает из фразы команду поиска и название поисковика."""
    value = _clean_text(text)
    value = _LEADING_COMMAND_RE.sub("", value)
    value = re.sub(
        r"^\s*(?:в\s+)?(?:интернете|сети)(?:\s+|$)",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^\s*в\s+(?:гугле|яндексе|google|yandex)(?:\s+|$)",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\s+в\s+(?:гугле|яндексе|google|yandex)\s*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:гугл\w*|google|яндекс\w*|yandex\w*)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = _BROWSER_STRIP_RE.sub(" ", value)
    value = _strip_query_noise(value)
    return value
