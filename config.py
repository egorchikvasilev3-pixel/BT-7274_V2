"""
config.py — константы и стили командного центра БТ-7274.
Ничего не импортирует из проекта, поэтому его можно менять без риска для остальных модулей.
"""

import os
import sys

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAIN_SCRIPT = os.path.join(BASE_DIR, "main.py")
HELMET_IMAGE = os.path.join(BASE_DIR, "helmet.webp")
LOCK_FILE = os.path.join(BASE_DIR, ".bt7274.lock")
CHAT_HISTORY_FILE = os.path.join(BASE_DIR, "chat_history.txt")
SHOTS_DIR = os.path.join(BASE_DIR, "shots")
CLIPS_DIR = os.path.join(BASE_DIR, "clips")

SCREENSHOT_PREFIXES = ("screenshot_", "bt_screenshot_")
VIDEO_PREFIXES = ("clip_", "bt_highlight_")

OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_MODEL = "llama3.2:3b"

WINDOW_TITLE = "БТ-7274 // КОМАНДНЫЙ ЦЕНТР"
HEADER_TEXT = "МОНИТОР СИСТЕМ VANGUARD"
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 480
HELMET_SIZE = 300
LINK_CHECK_INTERVAL_MS = 3000
THUMB_WIDTH = 190
THUMB_HEIGHT = 120

NEON_BLUE = "#4db8ff"
NEON_GREEN = "#39ff88"
ALERT_RED = "#ff4d5e"
WARN_AMBER = "#ffb84d"
MUTED_GREY = "#5a7088"
BG_TOP = "#0a1624"
BG_BOTTOM = "#05080d"
PANEL_BG = "rgba(10, 22, 36, 220)"
FONT_FAMILY = "Consolas"

CREATE_NO_WINDOW = 0x08000000

APP_STYLESHEET = f"""
QLabel {{
    background: transparent;
    font-family: {FONT_FAMILY};
}}
QPushButton {{
    background-color: {PANEL_BG};
    color: {NEON_BLUE};
    border: 2px solid {NEON_BLUE};
    border-radius: 4px;
    font-family: {FONT_FAMILY};
    font-size: 9pt;
    font-weight: bold;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: {NEON_BLUE};
    color: {BG_BOTTOM};
}}
QPushButton:pressed {{
    background-color: #1f6fa8;
    border-color: #bfe6ff;
    color: #ffffff;
}}
QPushButton:disabled {{
    color: {MUTED_GREY};
    border-color: {MUTED_GREY};
}}
QPushButton#exitButton {{
    color: {ALERT_RED};
    border-color: {ALERT_RED};
}}
QPushButton#exitButton:hover {{
    background-color: {ALERT_RED};
    color: {BG_BOTTOM};
}}
QPushButton#backButton {{
    color: {NEON_GREEN};
    border-color: {NEON_GREEN};
}}
QPushButton#backButton:hover {{
    background-color: {NEON_GREEN};
    color: {BG_BOTTOM};
}}
QTextEdit {{
    background-color: rgba(4, 10, 18, 230);
    color: {NEON_BLUE};
    border: 2px solid {NEON_BLUE};
    border-radius: 4px;
    font-family: {FONT_FAMILY};
    font-size: 10pt;
    padding: 8px;
}}
QScrollArea {{
    background: transparent;
    border: 1px solid {NEON_BLUE};
    border-radius: 4px;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: {BG_BOTTOM};
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {NEON_BLUE};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
