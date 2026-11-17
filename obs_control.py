"""
obs_control.py — управление OBS Studio через obs-websocket.
Отвечает за подключение, проверку 60 fps, старт/стоп записи и перенос
готового файла в папку clips проекта БТ-7274.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from obsws_python import ReqClient

LOG = logging.getLogger("bt7274")

OBS_HOST = "127.0.0.1"
OBS_PORT_FALLBACK = 4455
OBS_PASSWORD_FALLBACK = ""
OBS_CONNECT_TIMEOUT = 3.0
OBS_LAUNCH_TIMEOUT = 30.0
OBS_RECONNECT_TIMEOUT = 8.0
OBS_START_TIMEOUT = 6.0
OBS_FILE_FINALIZE_TIMEOUT = 20.0
OBS_TARGET_FPS = 60.0
OBS_CONFIG_PATH = (
    Path(os.environ.get("APPDATA", ""))
    / "obs-studio"
    / "plugin_config"
    / "obs-websocket"
    / "config.json"
)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class OBSControllerError(RuntimeError):
    """Понятная ошибка управления OBS для голосового ответа БТ."""


class OBSController:
    """Потокобезопасный контроллер OBS WebSocket."""

    def __init__(
        self,
        base_dir: Path,
        clips_dir: Path,
        auto_launch: bool = True,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._clips_dir = Path(clips_dir)
        self._auto_launch = auto_launch
        self._lock = threading.RLock()
        self._client: ReqClient | None = None
        self._started_at = 0.0
        self._recording = False
        self._clips_dir.mkdir(parents=True, exist_ok=True)

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._recording

    def start_recording(self) -> str:
        """Запускает запись OBS и проверяет, что она действительно пошла."""
        with self._lock:
            self._ensure_connected(allow_launch=True)
            if self._get_record_status():
                self._recording = True
                self._started_at = time.time()
                return "Запись уже идёт, пилот."

            self._ensure_target_fps()
            try:
                self._client.start_record()
            except Exception as error:
                self._drop_client()
                raise OBSControllerError(
                    f"OBS не смог начать запись: {error}"
                ) from error

            deadline = time.monotonic() + OBS_START_TIMEOUT
            while time.monotonic() < deadline:
                if self._get_record_status():
                    self._recording = True
                    self._started_at = time.time()
                    LOG.info("OBS: запись запущена")
                    return "OBS: запись запущена"
                time.sleep(0.2)
            raise OBSControllerError("OBS не подтвердил запуск записи.")

    def stop_recording(self, finalize_timeout: float | None = None) -> str:
        """Останавливает запись, ждёт финализации и переносит файл в clips."""
        with self._lock:
            timeout = (
                OBS_FILE_FINALIZE_TIMEOUT
                if finalize_timeout is None
                else max(0.5, float(finalize_timeout))
            )
            self._ensure_connected(allow_launch=False)
            if not self._get_record_status():
                self._recording = False
                return "Запись не активна, пилот."

            try:
                response = self._client.send("StopRecord", raw=True)
            except Exception as error:
                raise OBSControllerError(
                    f"OBS не смог остановить запись: {error}"
                ) from error

            self._recording = False
            output_path = ""
            if isinstance(response, dict):
                output_path = str(
                    response.get("outputPath")
                    or response.get("output_path")
                    or ""
                ).strip()

            source = Path(output_path) if output_path else self._find_latest_recording()
            if source is None:
                return "Запись остановлена, но OBS не сообщил путь файла."

            if not self._wait_for_recording_file(source, timeout):
                return f"Запись остановлена, но файл ещё не готов: {source}"

            destination = self._move_to_archive(source)
            LOG.info("OBS: запись сохранена в %s", destination)
            return str(destination)

    def pause_recording(self) -> str:
        """Ставит активную запись OBS на паузу."""
        with self._lock:
            self._ensure_connected(allow_launch=False)
            active, paused = self._get_record_state()
            if not active:
                self._recording = False
                return "Запись не активна, пилот."
            if paused:
                return "Запись уже на паузе, пилот."
            try:
                self._client.pause_record()
            except Exception as error:
                self._drop_client()
                raise OBSControllerError(
                    f"OBS не смог поставить запись на паузу: {error}"
                ) from error
            LOG.info("OBS: запись приостановлена")
            return "Запись приостановлена, пилот."

    def resume_recording(self) -> str:
        """Снимает активную запись OBS с паузы."""
        with self._lock:
            self._ensure_connected(allow_launch=False)
            active, paused = self._get_record_state()
            if not active:
                self._recording = False
                return "Запись не активна, пилот."
            if not paused:
                return "Запись уже идёт, пилот."
            try:
                self._client.resume_record()
            except Exception as error:
                self._drop_client()
                raise OBSControllerError(
                    f"OBS не смог продолжить запись: {error}"
                ) from error
            LOG.info("OBS: запись продолжена")
            return "Запись продолжена, пилот."

    @staticmethod
    def _response_text(response, *names: str) -> str:
        """Достаёт строковое поле из dataclass или словаря ответа OBS."""
        for name in names:
            if isinstance(response, dict):
                value = response.get(name)
            else:
                value = getattr(response, name, None)
            if value:
                return str(value)
        return ""

    def next_scene(self) -> str:
        """Переключает программу OBS на следующую сцену по кругу."""
        with self._lock:
            self._ensure_connected(allow_launch=False)
            try:
                response = self._client.get_scene_list()
            except Exception as error:
                self._drop_client()
                raise OBSControllerError(
                    f"OBS не отдал список сцен: {error}"
                ) from error
            scenes = list(
                response.get("scenes") or []
                if isinstance(response, dict)
                else getattr(response, "scenes", []) or []
            )
            names: list[str] = []
            for scene in scenes:
                if isinstance(scene, dict):
                    name = scene.get("sceneName") or scene.get("scene_name")
                else:
                    name = getattr(scene, "scene_name", None)
                if name:
                    names.append(str(name))
            if not names:
                raise OBSControllerError("В OBS нет доступных сцен, пилот.")
            current = self._response_text(
                response,
                "current_program_scene_name",
                "current_program_scene",
                "currentProgramSceneName",
                "currentProgramScene",
                "scene_name",
                "sceneName",
            )
            if not current:
                try:
                    current_response = self._client.get_current_program_scene()
                    current = self._response_text(
                        current_response,
                        "current_program_scene_name",
                        "current_program_scene",
                        "currentProgramSceneName",
                        "currentProgramScene",
                        "scene_name",
                        "sceneName",
                    )
                except Exception:
                    current = ""
            try:
                index = names.index(str(current))
            except ValueError:
                index = -1
            target = names[(index + 1) % len(names)]
            try:
                self._client.set_current_program_scene(target)
            except Exception as error:
                self._drop_client()
                raise OBSControllerError(
                    f"OBS не смог переключить сцену: {error}"
                ) from error
            LOG.info("OBS: сцена переключена на %s", target)
            return f"Сцена «{target}» активна, пилот."

    def disconnect(self) -> None:
        """Закрывает соединение с OBS, если оно было открыто."""
        with self._lock:
            self._drop_client()

    def _drop_client(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass

    def _ensure_connected(self, allow_launch: bool) -> None:
        if self._client is not None:
            try:
                self._client.get_version()
                return
            except Exception:
                self._drop_client()

        port, password = self._read_websocket_config()
        was_running = self._obs_process_running()
        try:
            self._client = ReqClient(
                host=OBS_HOST,
                port=port,
                password=password,
                timeout=OBS_CONNECT_TIMEOUT,
            )
            if self._wait_for_ready(OBS_RECONNECT_TIMEOUT):
                LOG.info("OBS WebSocket подключён: %s:%s", OBS_HOST, port)
                return
            LOG.warning("OBS WebSocket подключён, но OBS ещё не готов")
            self._drop_client()
        except Exception as error:
            LOG.warning("OBS WebSocket недоступен: %s", error)
            self._drop_client()

        if not was_running:
            if not self._auto_launch or not allow_launch:
                raise OBSControllerError("OBS не запущен, пилот.")
            self._launch_obs()
            timeout = OBS_LAUNCH_TIMEOUT
        else:
            timeout = OBS_RECONNECT_TIMEOUT

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.7)
            try:
                self._client = ReqClient(
                    host=OBS_HOST,
                    port=port,
                    password=password,
                    timeout=OBS_CONNECT_TIMEOUT,
                )
            except Exception:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if self._wait_for_ready(min(5.0, remaining)):
                LOG.info("OBS WebSocket подключён: %s:%s", OBS_HOST, port)
                return
            self._drop_client()

        if was_running:
            raise OBSControllerError(
                "OBS запущен, но WebSocket не отвечает. "
                "Проверь Tools → WebSocket Server Settings."
            )
        raise OBSControllerError(
            "OBS не запустился или WebSocket не отвечает, пилот."
        )

    def _wait_for_ready(self, timeout: float) -> bool:
        """Ждёт, пока OBS завершит инициализацию после подключения WebSocket."""
        deadline = time.monotonic() + max(0.5, float(timeout))
        while time.monotonic() < deadline:
            if self._client is None:
                return False
            try:
                self._client.get_version()
                return True
            except Exception:
                time.sleep(0.4)
        return False

    def _ensure_target_fps(self) -> None:
        """Проверяет FPS OBS и при необходимости выставляет 60/1."""
        try:
            video = self._client.get_video_settings()
        except Exception as error:
            self._drop_client()
            raise OBSControllerError(
                "Не удалось прочитать настройки видео OBS."
            ) from error

        numerator = int(getattr(video, "fps_numerator", 0) or 0)
        denominator = int(getattr(video, "fps_denominator", 1) or 1)
        current = numerator / denominator if denominator else 0.0
        if abs(current - OBS_TARGET_FPS) < 0.01:
            return

        if self._is_streaming():
            raise OBSControllerError(
                "OBS сейчас стримит. Не меняю FPS на ходу, пилот."
            )

        base_width = int(getattr(video, "base_width", 1920) or 1920)
        base_height = int(getattr(video, "base_height", 1080) or 1080)
        output_width = int(getattr(video, "output_width", base_width) or base_width)
        output_height = int(getattr(video, "output_height", base_height) or base_height)

        try:
            self._client.set_video_settings(
                int(OBS_TARGET_FPS),
                1,
                base_width,
                base_height,
                output_width,
                output_height,
            )
        except Exception as error:
            raise OBSControllerError(
                f"Не удалось установить 60 fps в OBS: {error}"
            ) from error

        time.sleep(0.4)
        try:
            video = self._client.get_video_settings()
        except Exception as error:
            self._drop_client()
            raise OBSControllerError(
                "Не удалось проверить FPS после настройки OBS."
            ) from error

        numerator = int(getattr(video, "fps_numerator", 0) or 0)
        denominator = int(getattr(video, "fps_denominator", 1) or 1)
        current = numerator / denominator if denominator else 0.0
        if abs(current - OBS_TARGET_FPS) >= 0.01:
            raise OBSControllerError("OBS не принял настройку 60 fps.")
        LOG.info("OBS: FPS установлен в 60")

    def _is_streaming(self) -> bool:
        try:
            return bool(self._client.get_stream_status().output_active)
        except Exception:
            return False

    def _get_record_status(self) -> bool:
        active, _ = self._get_record_state()
        return active

    def _get_record_state(self) -> tuple[bool, bool]:
        try:
            status = self._client.get_record_status()
        except Exception as error:
            self._drop_client()
            raise OBSControllerError(
                "OBS не отвечает на запрос статуса записи."
            ) from error
        active = bool(getattr(status, "output_active", False))
        paused = bool(getattr(status, "output_paused", False))
        return active, paused

    def _find_latest_recording(self) -> Path | None:
        directory: Path | None = None
        try:
            directory = Path(self._client.get_record_directory().record_directory)
        except Exception:
            LOG.exception("Не удалось получить папку записей OBS")

        if directory is None or not directory.is_dir():
            return None

        candidates: list[tuple[float, Path]] = []
        for extension in (".mp4", ".mkv", ".flv", ".mov", ".avi"):
            for path in directory.glob(f"*{extension}"):
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if self._started_at and modified < self._started_at - 3.0:
                    continue
                candidates.append((modified, path))

        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def _wait_for_recording_file(
        path: Path, timeout: float = OBS_FILE_FINALIZE_TIMEOUT
    ) -> bool:
        """Ждёт, пока OBS допишет и отпустит hybrid_mp4."""
        deadline = time.monotonic() + max(0.5, float(timeout))
        last_size = -1
        stable_since = 0.0
        while time.monotonic() < deadline:
            try:
                size = path.stat().st_size
            except OSError:
                time.sleep(0.25)
                continue

            if size > 1024 and size == last_size:
                if stable_since == 0.0:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 0.8:
                    try:
                        with path.open("rb") as recording:
                            recording.read(1)
                        return True
                    except OSError:
                        pass
            else:
                last_size = size
                stable_since = 0.0
            time.sleep(0.25)

        try:
            return path.exists() and path.stat().st_size > 1024
        except OSError:
            return False

    def _move_to_archive(self, source: Path) -> Path:
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower() or ".mp4"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = self._clips_dir / f"bt_highlight_{stamp}{suffix}"
        counter = 1
        while destination.exists():
            destination = self._clips_dir / f"bt_highlight_{stamp}_{counter}{suffix}"
            counter += 1

        try:
            if source.resolve() == destination.resolve():
                return destination
        except OSError:
            pass

        last_error: Exception | None = None
        for _ in range(6):
            try:
                shutil.move(str(source), str(destination))
                return destination
            except Exception as error:
                last_error = error
                time.sleep(0.5)

        raise OBSControllerError(
            f"Запись остановлена, но не удалось перенести файл в clips: {last_error}"
        ) from last_error

    @staticmethod
    def _read_websocket_config() -> tuple[int, str]:
        try:
            with OBS_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        except (OSError, ValueError):
            return OBS_PORT_FALLBACK, OBS_PASSWORD_FALLBACK

        try:
            port = int(data.get("server_port") or OBS_PORT_FALLBACK)
        except (TypeError, ValueError):
            port = OBS_PORT_FALLBACK
        password = str(data.get("server_password") or "").strip()
        if data.get("auth_required") is False:
            password = ""
        return port, password

    @staticmethod
    def _obs_process_running() -> bool:
        if os.name != "nt":
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "obs64.exe" in result.stdout.lower()

    def _launch_obs(self) -> None:
        executable = self._find_obs_executable()
        if executable is None:
            raise OBSControllerError(
                "OBS Studio не найден. Установи OBS или запусти его вручную, пилот."
            )
        LOG.info("OBS не запущен, запускаю: %s", executable)
        try:
            subprocess.Popen(
                [str(executable), "--disable-updater", "--minimize-to-tray"],
                cwd=str(executable.parent),
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as error:
            raise OBSControllerError(
                f"Не удалось запустить OBS: {error}"
            ) from error

    @classmethod
    def _find_obs_executable(cls) -> Path | None:
        candidates: list[Path] = []
        found = shutil.which("obs64.exe")
        if found:
            candidates.append(Path(found))

        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if not root:
                continue
            candidates.append(
                Path(root) / "obs-studio" / "bin" / "64bit" / "obs64.exe"
            )
            candidates.append(
                Path(root) / "Programs" / "obs-studio" / "bin" / "64bit" / "obs64.exe"
            )

        steam_roots = [
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam",
        ]
        for steam_root in steam_roots:
            candidates.append(
                steam_root
                / "steamapps"
                / "common"
                / "OBS Studio"
                / "bin"
                / "64bit"
                / "obs64.exe"
            )
            for library in cls._steam_libraries(steam_root / "steamapps" / "libraryfolders.vdf"):
                candidates.append(
                    library
                    / "steamapps"
                    / "common"
                    / "OBS Studio"
                    / "bin"
                    / "64bit"
                    / "obs64.exe"
                )

        try:
            import winreg

            for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(
                            root_key,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\OBS Studio",
                            0,
                            winreg.KEY_READ | view,
                        ) as key:
                            location, _ = winreg.QueryValueEx(key, "InstallLocation")
                            if location:
                                candidates.append(
                                    Path(location) / "bin" / "64bit" / "obs64.exe"
                                )
                    except OSError:
                        continue
        except ImportError:
            pass

        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
        return None

    @staticmethod
    def _steam_libraries(vdf_path: Path) -> list[Path]:
        try:
            text = vdf_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        libraries = []
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            raw_path = match.group(1).replace("\\\\", "\\")
            libraries.append(Path(raw_path))
        return libraries
