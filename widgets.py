"""
widgets.py — общие элементы интерфейса: неоновые надписи, кнопки, карточки превью и видео.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import ALERT_RED, MUTED_GREY, NEON_BLUE, NEON_GREEN, THUMB_HEIGHT, THUMB_WIDTH


def add_glow(widget, color=NEON_BLUE, radius=18):
    """Добавляет неоновое свечение к виджету."""
    glow = QGraphicsDropShadowEffect(widget)
    glow.setBlurRadius(radius)
    glow.setColor(QColor(color))
    glow.setOffset(0, 0)
    widget.setGraphicsEffect(glow)


def create_button(text, height=46, object_name=None):
    """Кнопка с фиксированной высотой и курсором-рукой."""
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedHeight(height)
    if object_name:
        button.setObjectName(object_name)
    return button


def create_back_button(text="НАЗАД В МЕНЮ"):
    """Зелёная кнопка возврата на главный экран."""
    return create_button(text, 38, "backButton")


def create_title(text, size=15):
    """Крупная неоновая надпись для заголовков экранов."""
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(f"color: {NEON_BLUE}; font-size: {size}pt; font-weight: bold;")
    add_glow(label)
    return label


def create_status_label(text, color, height=32):
    """Строка статуса в рамке выбранного цвета."""
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    label.setWordWrap(True)
    label.setFixedHeight(height)
    apply_status_style(label, color)
    return label


def apply_status_style(label, color):
    """Меняет цвет и рамку у строки статуса."""
    label.setStyleSheet(
        f"color: {color}; font-size: 9pt; font-weight: bold;"
        f" border: 1px solid {color}; border-radius: 4px; padding: 4px;"
    )


def _cut_points(rect, cut):
    """Возвращает углы панели со срезанными углами."""
    x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
    return [
        QPointF(x1 + cut, y1),
        QPointF(x2 - cut, y1),
        QPointF(x2, y1 + cut),
        QPointF(x2, y2 - cut),
        QPointF(x2 - cut, y2),
        QPointF(x1 + cut, y2),
        QPointF(x1, y2 - cut),
        QPointF(x1, y1 + cut),
    ]


class CommandRow(QPushButton):
    """HUD-строка команды: номер, название, подпись и акцентная полоса."""

    def __init__(
        self,
        index,
        title,
        subtitle,
        accent=NEON_BLUE,
        primary=False,
        height=40,
        parent=None,
    ):
        super().__init__(parent)
        self._index = str(index)
        self._title = str(title)
        self._subtitle = str(subtitle)
        self._accent = QColor(accent)
        self._primary = bool(primary)
        self._hover = False
        self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.setToolTip(self._subtitle)

    def sizeHint(self):
        return QSize(380, self.height())

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        enabled = self.isEnabled()
        accent = QColor(self._accent) if enabled else QColor(MUTED_GREY)
        active = (self._primary or self._hover) and enabled

        points = _cut_points(rect, 8.0)
        fill = QColor(12, 40, 64, 235) if active else QColor(10, 22, 36, 210)
        border = accent if active else QColor(60, 100, 140, 160)
        painter.setBrush(fill)
        painter.setPen(QPen(border, 2.0 if active else 1.0))
        painter.drawPolygon(QPolygonF(points))

        painter.fillRect(
            QRectF(rect.left() + 1.0, rect.top() + 7.0, 4.0, rect.height() - 14.0),
            accent,
        )

        index_font = QFont("Consolas", 8)
        index_font.setBold(True)
        painter.setFont(index_font)
        painter.setPen(accent)
        painter.drawText(
            QRectF(rect.left() + 14.0, rect.top() + 5.0, 28.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._index,
        )

        title_font = QFont("Consolas", 9)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#eafcff") if active else QColor(NEON_BLUE))
        painter.drawText(
            QRectF(rect.left() + 44.0, rect.top() + 4.0, rect.width() - 74.0, 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title,
        )

        subtitle_font = QFont("Consolas", 7)
        painter.setFont(subtitle_font)
        painter.setPen(QColor(MUTED_GREY))
        painter.drawText(
            QRectF(rect.left() + 44.0, rect.top() + 21.0, rect.width() - 74.0, 14.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._subtitle,
        )

        arrow_font = QFont("Consolas", 15)
        arrow_font.setBold(True)
        painter.setFont(arrow_font)
        painter.setPen(accent)
        painter.drawText(
            QRectF(rect.right() - 26.0, rect.top(), 18.0, rect.height()),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "\u203a",
        )
        painter.end()


def create_telemetry_chip(label, value, color=NEON_BLUE):
    """Возвращает виджет телеметрии и ссылку на метку значения."""
    host = QWidget()
    host.setMinimumWidth(96)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    caption = QLabel(label)
    caption.setStyleSheet(
        f"color: {MUTED_GREY}; background: transparent;"
        " font-family: Consolas; font-size: 7pt;"
    )
    value_label = QLabel(value)
    value_label.setStyleSheet(
        f"color: {color}; background: transparent;"
        " font-family: Consolas; font-size: 8.5pt; font-weight: bold;"
    )
    layout.addWidget(caption)
    layout.addWidget(value_label)
    return host, value_label


def set_telemetry_value(label, value, color):
    """Обновляет значение телеметрии и его цвет."""
    label.setText(value)
    label.setStyleSheet(
        f"color: {color}; background: transparent;"
        " font-family: Consolas; font-size: 8.5pt; font-weight: bold;"
    )


class PreviewCard(QFrame):
    """Карточка скриншота: миниатюра и подпись. Клик посылает сигнал с путём к файлу."""

    clicked = Signal(str)

    def __init__(self, path, caption):
        super().__init__()
        self.path = path
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"PreviewCard {{ border: 1px solid {NEON_BLUE}; border-radius: 4px;"
            f" background: rgba(10, 22, 36, 200); }}"
            f"PreviewCard:hover {{ border: 2px solid {NEON_GREEN}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        thumb = QLabel()
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT)
        pixmap = QPixmap(path)
        if pixmap.isNull():
            thumb.setText("[НЕТ ПРЕВЬЮ]")
            thumb.setStyleSheet(f"color: {ALERT_RED}; font-size: 8pt;")
        else:
            thumb.setPixmap(
                pixmap.scaled(THUMB_WIDTH, THUMB_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        layout.addWidget(thumb)

        text = QLabel(caption)
        text.setAlignment(Qt.AlignCenter)
        text.setStyleSheet(f"color: {NEON_BLUE}; font-size: 8pt;")
        layout.addWidget(text)

    def mousePressEvent(self, event):
        """Клик по карточке открывает скриншот во весь размер."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(event)


class VideoRow(QFrame):
    """Строка списка видео: неоновая иконка плеера, имя, дата. Клик посылает путь к файлу."""

    clicked = Signal(str)

    def __init__(self, path, name, date_text):
        super().__init__()
        self.path = path
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"VideoRow {{ border: 1px solid {NEON_BLUE}; border-radius: 4px;"
            f" background: rgba(10, 22, 36, 200); }}"
            f"VideoRow:hover {{ border: 2px solid {NEON_GREEN}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        icon = QLabel("\u25B6")
        icon.setFixedWidth(34)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"color: {NEON_GREEN}; font-size: 16pt; font-weight: bold;"
            f" border: 2px solid {NEON_GREEN}; border-radius: 17px;"
        )
        layout.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(2)
        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {NEON_BLUE}; font-size: 9pt; font-weight: bold;")
        date_label = QLabel(date_text)
        date_label.setStyleSheet(f"color: {MUTED_GREY}; font-size: 8pt;")
        info.addWidget(name_label)
        info.addWidget(date_label)
        layout.addLayout(info, 1)

    def mousePressEvent(self, event):
        """Клик по строке запускает видео."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(event)
