"""
launcher.py — главное окно «БТ-7274 // КОМАНДНЫЙ ЦЕНТР».
Собирает экраны из screens.py в QStackedWidget и связывает их с логикой из core.py.
Запуск: python launcher.py
"""

import os
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from config import (
    APP_STYLESHEET,
    ALERT_RED,
    BG_BOTTOM,
    BG_TOP,
    LINK_CHECK_INTERVAL_MS,
    MAIN_SCRIPT,
    BASE_DIR,
    MUTED_GREY,
    NEON_BLUE,
    NEON_GREEN,
    WARN_AMBER,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
)
from core import (
    CREATE_NO_WINDOW,
    append_chat_line,
    check_ollama,
    collect_telemetry,
    ensure_chat_history,
    is_bt_process,
    list_screenshots,
    list_videos,
    open_with_default_app,
    read_lock_pid,
    resolve_python_gui,
    terminate_bt_by_lock,
)
from screens import GalleryScreen, HistoryScreen, MenuScreen, VideoScreen

SHUTDOWN_REQUEST_FILE = os.path.join(BASE_DIR, "data", "shutdown.request")
GRACEFUL_SHUTDOWN_SECONDS = 5.0
TELEMETRY_INTERVAL_SECONDS = 1.6


def request_bt_shutdown():
    """Создаёт флаг, который main.py опрашивает и завершается штатно."""
    try:
        os.makedirs(os.path.dirname(SHUTDOWN_REQUEST_FILE), exist_ok=True)
        with open(SHUTDOWN_REQUEST_FILE, "w", encoding="utf-8") as flag:
            flag.write("shutdown\n")
        return True
    except OSError:
        return False


def clear_bt_shutdown_request():
    """Удаляет флаг завершения, чтобы он не сработал при следующем запуске."""
    try:
        os.remove(SHUTDOWN_REQUEST_FILE)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def build_agent_command():
    """Возвращает команду запуска агента: встроенный exe или main.py через Python."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--agent"]
    return [resolve_python_gui(), MAIN_SCRIPT]


class OllamaBridge(QObject):
    """Передаёт результат проверки Ollama из фонового потока в главный поток GUI."""

    checked = Signal(bool, bool)


class TelemetryBridge(QObject):
    """Передаёт телеметрию из фонового потока в главный поток GUI."""

    updated = Signal(dict)


class LauncherWindow(QWidget):
    """Главное окно лаунчера: стек экранов, фон, управление БТ и проверка Ollama."""

    def __init__(self):
        super().__init__()
        self.proc = None
        self.bridge = OllamaBridge(self)
        self.bridge.checked.connect(self.on_ollama_checked)
        self.telemetry_bridge = TelemetryBridge(self)

        self.setWindowTitle(WINDOW_TITLE)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setStyleSheet(APP_STYLESHEET)

        self.stack = QStackedWidget()
        self.menu = MenuScreen()
        self.history = HistoryScreen()
        self.gallery = GalleryScreen()
        self.videos = VideoScreen()
        for screen in (self.menu, self.history, self.gallery, self.videos):
            self.stack.addWidget(screen)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.connect_signals()
        ensure_chat_history()

        self.link_timer = QTimer(self)
        self.link_timer.timeout.connect(self.refresh_link_status)
        self.link_timer.start(LINK_CHECK_INTERVAL_MS)
        self.refresh_link_status()

        self.telemetry_bridge.updated.connect(self.menu.update_telemetry)
        self._telemetry_stop = threading.Event()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_worker,
            name="bt-telemetry",
            daemon=True,
        )
        self._telemetry_thread.start()
        self.center_on_screen()

    def connect_signals(self):
        """Связывает кнопки экранов с действиями лаунчера."""
        self.menu.start_requested.connect(self.start_bt)
        self.menu.history_requested.connect(self.show_history)
        self.menu.screenshots_requested.connect(self.show_gallery)
        self.menu.videos_requested.connect(self.show_videos)
        self.menu.ollama_requested.connect(self.check_ollama_async)
        self.menu.exit_requested.connect(self.exit_launcher)
        self.history.back_requested.connect(self.show_menu)
        self.gallery.back_requested.connect(self.show_menu)
        self.videos.back_requested.connect(self.show_menu)
        self.videos.video_requested.connect(self.play_video)

    def center_on_screen(self):
        """Центрирует окно по доступной области основного экрана Windows."""
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    def paintEvent(self, event):
        """Рисует фон, сканлайны и угловые маркеры кабины титана."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(BG_TOP))
        gradient.setColorAt(1.0, QColor(BG_BOTTOM))
        painter.fillRect(self.rect(), QBrush(gradient))

        scan_pen = QPen(QColor(77, 184, 255, 22))
        scan_pen.setWidth(1)
        painter.setPen(scan_pen)
        for y in range(0, self.height(), 4):
            painter.drawLine(0, y, self.width(), y)

        corner_pen = QPen(QColor(NEON_BLUE))
        corner_pen.setWidth(2)
        painter.setPen(corner_pen)
        margin, length = 8, 22
        w, h = self.width(), self.height()
        painter.drawLine(margin, margin, margin + length, margin)
        painter.drawLine(margin, margin, margin, margin + length)
        painter.drawLine(w - margin, margin, w - margin - length, margin)
        painter.drawLine(w - margin, margin, w - margin, margin + length)
        painter.drawLine(margin, h - margin, margin + length, h - margin)
        painter.drawLine(margin, h - margin, margin, h - margin - length)
        painter.drawLine(w - margin, h - margin, w - margin - length, h - margin)
        painter.drawLine(w - margin, h - margin, w - margin, h - margin - length)
        painter.end()

    def is_bt_running(self):
        """БТ считается активным, если запущен из лаунчера или жив PID из lock-файла."""
        if self.proc is not None and self.proc.poll() is None:
            return True
        self.proc = None
        return is_bt_process(read_lock_pid())

    def refresh_link_status(self):
        """Обновляет индикатор связи на главном экране."""
        self.menu.set_link_active(self.is_bt_running())

    def show_menu(self):
        """Возвращает главный экран."""
        self.stack.setCurrentWidget(self.menu)

    def show_history(self):
        """Открывает встроенный журнал синхронизации."""
        self.history.reload()
        self.stack.setCurrentWidget(self.history)

    def show_gallery(self):
        """Открывает встроенную галерею скриншотов."""
        self.gallery.reload()
        self.stack.setCurrentWidget(self.gallery)
        self.menu.show_log(f"АРХИВ ОТКРЫТ. СНИМКОВ: {len(list_screenshots())}", NEON_BLUE)

    def show_videos(self):
        """Открывает встроенный список видео."""
        self.videos.reload()
        self.stack.setCurrentWidget(self.videos)
        self.menu.show_log(f"АРХИВ ВИДЕО ОТКРЫТ. КЛИПОВ: {len(list_videos())}", NEON_BLUE)

    def play_video(self, path):
        """Запускает видео стандартным плеером Windows; список остаётся внутри лаунчера."""
        try:
            open_with_default_app(path)
        except OSError as error:
            self.menu.show_log(f"ОШИБКА ВОСПРОИЗВЕДЕНИЯ: {error}", ALERT_RED)

    def start_bt(self):
        """Запускает main.py в фоне через subprocess.Popen без консоли."""
        if self.is_bt_running():
            self.menu.show_log("БТ УЖЕ АКТИВЕН. ПОВТОРНАЯ ИНИЦИАЛИЗАЦИЯ НЕ ТРЕБУЕТСЯ.", NEON_GREEN)
            self.refresh_link_status()
            return
        clear_bt_shutdown_request()
        try:
            self.proc = subprocess.Popen(
                build_agent_command(),
                cwd=BASE_DIR,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as error:
            self.proc = None
            self.menu.show_log(f"ОШИБКА ЗАПУСКА НЕЙРОЛИНКА: {error}", ALERT_RED)
            return
        self.menu.show_log("НЕЙРОЛИНК ИНИЦИАЛИЗИРУЕТСЯ...", NEON_BLUE)
        append_chat_line("СИСТЕМА", "Нейролинк инициализирован лаунчером.")
        self.refresh_link_status()

    def check_ollama_async(self):
        """Проверяет Ollama в фоновом потоке, чтобы окно не зависало."""
        self.menu.ollama_button.setEnabled(False)
        self.menu.show_log("ЗАПРОС К ДАТА-ЯДРАМ...", NEON_BLUE)
        worker = threading.Thread(target=self.run_ollama_check, daemon=True)
        worker.start()

    def run_ollama_check(self):
        """Тело фонового потока: выполняет запрос и отправляет результат через сигнал."""
        reachable, model_found = check_ollama()
        self.bridge.checked.emit(reachable, model_found)

    def _telemetry_worker(self):
        """Собирает телеметрию в фоне; GPU опрашивается через цикл и кэшируется."""
        cycle = 0
        gpu_cache = {}
        while not self._telemetry_stop.is_set():
            data = collect_telemetry(include_gpu=(cycle % 2 == 0))
            if self._telemetry_stop.is_set():
                break
            if data:
                has_gpu = isinstance(data.get("gpu_util"), (int, float)) and isinstance(
                    data.get("gpu_temp"), (int, float)
                )
                if has_gpu:
                    gpu_cache = {
                        "gpu_util": data["gpu_util"],
                        "gpu_temp": data["gpu_temp"],
                    }
                elif gpu_cache:
                    data.update(gpu_cache)
                self.telemetry_bridge.updated.emit(data)
            cycle += 1
            if self._telemetry_stop.wait(TELEMETRY_INTERVAL_SECONDS):
                break

    def on_ollama_checked(self, reachable, model_found):
        """Выводит результат проверки Ollama в журнал главного экрана."""
        self.menu.ollama_button.setEnabled(True)
        if not reachable:
            self.menu.show_log("ОШИБКА: ДАТА-ЯДРА ОТКЛЮЧЕНЫ", ALERT_RED)
        elif model_found:
            self.menu.show_log("СТАТУС МОЗГА: СТАБИЛЕН (llama3.2:3b найден)", NEON_GREEN)
        else:
            self.menu.show_log("СТАТУС МОЗГА: ДАТА-ЯДРО ОНЛАЙН, МОДЕЛЬ НЕ НАЙДЕНА", WARN_AMBER)

    def shutdown_bt(self):
        """Просит БТ завершиться штатно и только затем добивает процесс."""
        pid = read_lock_pid()
        if not self.is_bt_running():
            self.proc = None
            clear_bt_shutdown_request()
            return
        requested = request_bt_shutdown()
        if not requested:
            self.menu.show_log(
                "ФЛАГ ЗАВЕРШЕНИЯ НЕ СОЗДАН. ПРИНУДИТЕЛЬНАЯ ОСТАНОВКА.", WARN_AMBER
            )
        deadline = time.monotonic() + GRACEFUL_SHUTDOWN_SECONDS
        while requested and time.monotonic() < deadline:
            if self.proc is not None:
                if self.proc.poll() is not None:
                    break
            elif pid and not is_bt_process(pid):
                break
            time.sleep(0.2)
        if self.proc is not None and self.proc.poll() is None:
            if requested:
                self.menu.show_log(
                    "ШТАТНОЕ ЗАВЕРШЕНИЕ НЕ ОТВЕТИЛО. ПРИНУДИТЕЛЬНАЯ ОСТАНОВКА.",
                    WARN_AMBER,
                )
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        terminate_bt_by_lock()
        clear_bt_shutdown_request()

    def exit_launcher(self):
        """Завершает БТ и весь лаунчер."""
        self._telemetry_stop.set()
        self.link_timer.stop()
        self.shutdown_bt()
        QApplication.quit()

    def closeEvent(self, event):
        """Закрытие окна крестиком работает так же, как кнопка выхода."""
        self.exit_launcher()
        event.accept()


def main():
    """Точка входа: командный центр или встроенный голосовой агент в режиме --agent."""
    if "--agent" in sys.argv:
        # Встроенный exe запускает сам себя без внешнего Python и main.py.
        sys.argv = [argument for argument in sys.argv if argument != "--agent"]
        from main import main as agent_main

        raise SystemExit(agent_main())
    app = QApplication(sys.argv)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
