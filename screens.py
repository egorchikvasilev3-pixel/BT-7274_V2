"""
screens.py — четыре экрана командного центра: главное меню, журнал, галерея скриншотов, список видео.
Экраны не запускают процессы сами: действия передаются наверх через сигналы.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import (
    ALERT_RED,
    HELMET_IMAGE,
    MUTED_GREY,
    NEON_BLUE,
    NEON_GREEN,
    WARN_AMBER,
)
from core import format_mtime, list_screenshots, list_videos, open_with_default_app, read_chat_entries
from widgets import (
    CommandRow,
    PreviewCard,
    VideoRow,
    add_glow,
    apply_status_style,
    create_back_button,
    create_button,
    create_status_label,
    create_telemetry_chip,
    create_title,
    set_telemetry_value,
)


class MenuScreen(QWidget):
    """Главное меню: карточка BT, HUD-команды, телеметрия и статус."""

    start_requested = Signal()
    history_requested = Signal()
    screenshots_requested = Signal()
    videos_requested = Signal()
    ollama_requested = Signal()
    exit_requested = Signal()

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 12)
        root.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("BT-7274")
        title.setStyleSheet(
            "color: #eafcff; background: transparent;"
            " font-family: Bahnschrift; font-size: 19pt; font-weight: 700;"
        )
        add_glow(title, NEON_BLUE, 18)
        subtitle = QLabel("// VANGUARD COMMAND CENTER")
        subtitle.setStyleSheet(
            f"color: {MUTED_GREY}; background: transparent;"
            " font-family: Consolas; font-size: 8pt; font-weight: bold;"
        )
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.link_indicator = create_status_label("[СВЯЗЬ НЕТ]", MUTED_GREY, 26)
        self.link_indicator.setFixedWidth(130)
        header.addWidget(self.link_indicator)
        root.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(77, 184, 255, 90); border: none;")
        root.addWidget(line)

        body = QHBoxLayout()
        body.setSpacing(18)

        left = QWidget()
        left.setFixedWidth(300)
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.setSpacing(2)

        helmet = QLabel()
        helmet.setAlignment(Qt.AlignmentFlag.AlignCenter)
        helmet.setFixedSize(300, 169)
        pixmap = QPixmap(HELMET_IMAGE)
        if pixmap.isNull():
            helmet.setText("[НЕТ ОБРАЗА ШЛЕМА]")
            helmet.setStyleSheet(f"color: {MUTED_GREY}; font-size: 8pt;")
        else:
            helmet.setPixmap(
                pixmap.scaled(
                    300,
                    169,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        add_glow(helmet, NEON_BLUE, 28)
        left_box.addWidget(helmet)

        card_name = QLabel("BT-7274")
        card_name.setStyleSheet(
            "color: #eafcff; background: transparent;"
            " font-family: Bahnschrift; font-size: 21pt; font-weight: 700;"
        )
        left_box.addWidget(card_name)
        card_class = QLabel("VANGUARD CLASS")
        card_class.setStyleSheet(
            f"color: {NEON_BLUE}; background: transparent;"
            " font-family: Consolas; font-size: 8pt; font-weight: bold;"
        )
        left_box.addWidget(card_class)
        card_pilot = QLabel("PILOT: ADMIN")
        card_pilot.setStyleSheet(
            f"color: {MUTED_GREY}; background: transparent;"
            " font-family: Consolas; font-size: 8pt;"
        )
        left_box.addWidget(card_pilot)
        left_box.addSpacing(6)

        state_row = QHBoxLayout()
        state_row.setSpacing(6)
        state_caption = QLabel("СОСТОЯНИЕ:")
        state_caption.setStyleSheet(
            f"color: {MUTED_GREY}; background: transparent;"
            " font-family: Consolas; font-size: 7.5pt;"
        )
        self.state_value = QLabel("ГОТОВ")
        self.state_value.setStyleSheet(
            f"color: {NEON_GREEN}; background: transparent;"
            " font-family: Consolas; font-size: 8pt; font-weight: bold;"
        )
        state_row.addWidget(state_caption)
        state_row.addWidget(self.state_value)
        state_row.addStretch(1)
        left_box.addLayout(state_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_caption = QLabel("РЕЖИМ:")
        mode_caption.setStyleSheet(
            f"color: {MUTED_GREY}; background: transparent;"
            " font-family: Consolas; font-size: 7.5pt;"
        )
        self.mode_value = QLabel("ОЖИДАНИЕ F1")
        self.mode_value.setStyleSheet(
            f"color: {NEON_BLUE}; background: transparent;"
            " font-family: Consolas; font-size: 8pt; font-weight: bold;"
        )
        mode_row.addWidget(mode_caption)
        mode_row.addWidget(self.mode_value)
        mode_row.addStretch(1)
        left_box.addLayout(mode_row)
        left_box.addStretch(1)
        body.addWidget(left)

        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.setSpacing(4)
        self.start_button = CommandRow(
            "01",
            "ИНИЦИАЛИЗАЦИЯ НЕЙРОЛИНКА",
            "ЗАПУСК БТ",
            NEON_BLUE,
            True,
            46,
        )
        self.start_button.clicked.connect(self.start_requested)
        right_box.addWidget(self.start_button)

        self.history_button = CommandRow(
            "02", "ЖУРНАЛ СИНХРОНИЗАЦИИ", "ИСТОРИЯ ЧАТА"
        )
        self.history_button.clicked.connect(self.history_requested)
        right_box.addWidget(self.history_button)

        self.screenshots_button = CommandRow(
            "03", "АРХИВ ВИЗУАЛЬНЫХ ДАННЫХ", "СКРИНШОТЫ"
        )
        self.screenshots_button.clicked.connect(self.screenshots_requested)
        right_box.addWidget(self.screenshots_button)

        self.videos_button = CommandRow(
            "04", "АРХИВ ВИДЕОПОТОКА", "ХАЙЛАЙТЫ"
        )
        self.videos_button.clicked.connect(self.videos_requested)
        right_box.addWidget(self.videos_button)

        self.ollama_button = CommandRow(
            "05", "ДИАГНОСТИКА ДАТА-ЯДЕР", "OLLAMA"
        )
        self.ollama_button.clicked.connect(self.ollama_requested)
        right_box.addWidget(self.ollama_button)

        self.exit_button = CommandRow(
            "!!", "РАЗОРВАТЬ СОЕДИНЕНИЕ", "ВЫХОД", ALERT_RED
        )
        self.exit_button.clicked.connect(self.exit_requested)
        right_box.addWidget(self.exit_button)
        right_box.addStretch(1)
        body.addWidget(right, 1)
        root.addLayout(body, 1)

        telemetry = QHBoxLayout()
        telemetry.setSpacing(10)
        cpu_chip, self.cpu_value = create_telemetry_chip("CPU", "--%")
        ram_chip, self.ram_value = create_telemetry_chip("RAM", "-- / -- GB")
        gpu_chip, self.gpu_value = create_telemetry_chip("GPU", "N/A", MUTED_GREY)
        ollama_chip, self.ollama_value = create_telemetry_chip(
            "OLLAMA", "OFF", MUTED_GREY
        )
        obs_chip, self.obs_value = create_telemetry_chip("OBS", "OFF", MUTED_GREY)
        for chip in (cpu_chip, ram_chip, gpu_chip, ollama_chip, obs_chip):
            telemetry.addWidget(chip, 1)
        root.addLayout(telemetry)

        self.log_label = create_status_label(
            "СИСТЕМЫ В НОРМЕ. ОЖИДАНИЕ КОМАНДЫ ПИЛОТА.",
            NEON_BLUE,
            32,
        )
        root.addWidget(self.log_label)

    def set_link_active(self, active):
        """Переключает индикатор связи и состояние БТ."""
        if active:
            self.link_indicator.setText("[СВЯЗЬ АКТИВНА]")
            apply_status_style(self.link_indicator, NEON_GREEN)
            self.state_value.setText("АКТИВЕН")
            self.state_value.setStyleSheet(
                f"color: {NEON_GREEN}; background: transparent;"
                " font-family: Consolas; font-size: 8pt; font-weight: bold;"
            )
            self.mode_value.setText("КАНАЛ F1")
            self.mode_value.setStyleSheet(
                f"color: {NEON_GREEN}; background: transparent;"
                " font-family: Consolas; font-size: 8pt; font-weight: bold;"
            )
        else:
            self.link_indicator.setText("[СВЯЗЬ НЕТ]")
            apply_status_style(self.link_indicator, MUTED_GREY)
            self.state_value.setText("ГОТОВ")
            self.state_value.setStyleSheet(
                f"color: {NEON_GREEN}; background: transparent;"
                " font-family: Consolas; font-size: 8pt; font-weight: bold;"
            )
            self.mode_value.setText("ОЖИДАНИЕ F1")
            self.mode_value.setStyleSheet(
                f"color: {NEON_BLUE}; background: transparent;"
                " font-family: Consolas; font-size: 8pt; font-weight: bold;"
            )

    def update_telemetry(self, data):
        """Обновляет нижнюю панель телеметрии."""
        if not isinstance(data, dict):
            return
        cpu = data.get("cpu")
        if isinstance(cpu, (int, float)):
            cpu_color = NEON_GREEN if cpu < 70 else WARN_AMBER
            set_telemetry_value(self.cpu_value, f"{cpu:.0f}%", cpu_color)
        ram_used = data.get("ram_used")
        ram_total = data.get("ram_total")
        if isinstance(ram_used, (int, float)) and isinstance(ram_total, (int, float)):
            ratio = ram_used / max(0.1, ram_total)
            ram_color = NEON_GREEN if ratio < 0.85 else WARN_AMBER
            set_telemetry_value(
                self.ram_value,
                f"{ram_used:.1f} / {ram_total:.1f} GB",
                ram_color,
            )
        gpu_temp = data.get("gpu_temp")
        gpu_util = data.get("gpu_util")
        if isinstance(gpu_temp, (int, float)) and isinstance(gpu_util, (int, float)):
            gpu_color = NEON_BLUE if gpu_temp < 80 else WARN_AMBER
            set_telemetry_value(
                self.gpu_value,
                f"{gpu_temp:.0f}°C {gpu_util:.0f}%",
                gpu_color,
            )
        ollama = data.get("ollama")
        if isinstance(ollama, bool):
            set_telemetry_value(
                self.ollama_value,
                "ONLINE" if ollama else "OFF",
                NEON_GREEN if ollama else MUTED_GREY,
            )
        obs = data.get("obs")
        if isinstance(obs, bool):
            set_telemetry_value(
                self.obs_value,
                "ON" if obs else "OFF",
                NEON_GREEN if obs else MUTED_GREY,
            )

    def show_log(self, message, color):
        """Выводит сообщение в журнал главного экрана."""
        self.log_label.setText(message)
        apply_status_style(self.log_label, color)


class HistoryScreen(QWidget):
    """Журнал синхронизации: только чтение, неоновый текст из chat_history.txt."""

    back_requested = Signal()

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        root.addWidget(create_title("ЖУРНАЛ СИНХРОНИЗАЦИИ", 13))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        root.addWidget(self.text, 1)

        self.counter = create_status_label("", MUTED_GREY, 28)
        root.addWidget(self.counter)

        back = create_back_button()
        back.clicked.connect(self.back_requested)
        root.addWidget(back)

    def reload(self):
        """Перечитывает chat_history.txt и выводит записи в формате [ВРЕМЯ] Говорящий: текст."""
        entries = read_chat_entries()
        lines = []
        for time_text, speaker, text in entries:
            lines.append(f"[{time_text}] {speaker}: {text}")
        if lines:
            self.text.setPlainText("\n".join(lines))
        else:
            self.text.setPlainText("[ЖУРНАЛ ПУСТ. ОЖИДАНИЕ ПЕРВОЙ СИНХРОНИЗАЦИИ.]")
        apply_status_style(self.counter, NEON_BLUE)
        self.counter.setText(f"ЗАПИСЕЙ В ЖУРНАЛЕ: {len(entries)}")


class ImageViewer(QDialog):
    """Окно просмотра скриншота во весь размер, с подгонкой под экран."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        self.setStyleSheet(f"QDialog {{ background: #05080d; border: 2px solid {NEON_BLUE}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(path)
        screen = self.screen().availableGeometry()
        max_width = int(screen.width() * 0.85)
        max_height = int(screen.height() * 0.85)
        if pixmap.isNull():
            label.setText("[НЕ УДАЛОСЬ ОТКРЫТЬ ИЗОБРАЖЕНИЕ]")
            label.setStyleSheet(f"color: {ALERT_RED}; font-size: 12pt;")
        else:
            label.setPixmap(pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(label)
        self.resize(min(pixmap.width(), max_width) + 20, min(pixmap.height(), max_height) + 20)


class GalleryScreen(QWidget):
    """Галерея скриншотов: сетка превью, клик открывает изображение во весь размер."""

    back_requested = Signal()

    def __init__(self):
        super().__init__()
        self.viewers = []
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        root.addWidget(create_title("АРХИВ ВИЗУАЛЬНЫХ ДАННЫХ", 13))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        self.counter = create_status_label("", MUTED_GREY, 28)
        root.addWidget(self.counter)

        back = create_back_button()
        back.clicked.connect(self.back_requested)
        root.addWidget(back)

    def reload(self):
        """Пересобирает сетку превью из shots/ и старых PNG в корне проекта."""
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        paths = list_screenshots()
        for index, path in enumerate(paths):
            card = PreviewCard(path, os.path.basename(path))
            card.clicked.connect(self.open_viewer)
            self.grid.addWidget(card, index // 2, index % 2)

        apply_status_style(self.counter, NEON_BLUE)
        self.counter.setText(f"СНИМКОВ ЭКРАНА НА ДИСКЕ: {len(paths)}")

    def open_viewer(self, path):
        """Открывает скриншот во весь размер в отдельном окне лаунчера."""
        viewer = ImageViewer(path, self)
        self.viewers.append(viewer)
        viewer.exec()


class VideoScreen(QWidget):
    """Список видео из clips/ и старых файлов в корне. Клик запускает видео."""

    back_requested = Signal()
    video_requested = Signal(str)

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        root.addWidget(create_title("АРХИВ ВИДЕОПОТОКА", 13))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setSpacing(6)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        self.counter = create_status_label("", MUTED_GREY, 28)
        root.addWidget(self.counter)

        back = create_back_button()
        back.clicked.connect(self.back_requested)
        root.addWidget(back)

    def reload(self):
        """Пересобирает список видео с датами создания файлов."""
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        paths = list_videos()
        for path in paths:
            row = VideoRow(path, os.path.basename(path), format_mtime(path))
            row.clicked.connect(self.video_requested)
            self.list_layout.addWidget(row)

        apply_status_style(self.counter, NEON_BLUE)
        self.counter.setText(f"ВИДЕОКЛИПОВ НА ДИСКЕ: {len(paths)}")
