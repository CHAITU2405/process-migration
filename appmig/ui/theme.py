"""Dark theme, applied application-wide."""
from __future__ import annotations

import hashlib

# Palette
BG = "#12141a"
BG_ELEVATED = "#1a1d26"
BG_CARD = "#1f232e"
BG_HOVER = "#262b38"
BORDER = "#2c3140"
TEXT = "#e6e9f0"
TEXT_DIM = "#8f97a8"
TEXT_FAINT = "#5f6779"
ACCENT = "#4d8dff"
ACCENT_HOVER = "#639bff"
SUCCESS = "#3ecf8e"
WARNING = "#e8b84b"
DANGER = "#ef5f5f"

FIDELITY_COLORS = {
    "high": SUCCESS,
    "partial": WARNING,
    "fresh": TEXT_FAINT,
}

FIDELITY_LABELS = {
    "high": "Full session",
    "partial": "Partial",
    "fresh": "Fresh start",
}

_AVATAR_COLORS = [
    "#4d8dff", "#3ecf8e", "#e8b84b", "#ef5f5f", "#a97bff",
    "#43c9d6", "#ff8f5c", "#7ec74f", "#e56ab3", "#5f8fd6",
]


def avatar_color(name: str) -> str:
    """Stable per-application colour, so the same app always looks the same."""
    digest = hashlib.md5(name.lower().encode()).digest()
    return _AVATAR_COLORS[digest[0] % len(_AVATAR_COLORS)]


STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
}}

QMainWindow, QDialog {{ background: {BG}; }}

/* Labels must not paint the page background over a card. */
QLabel {{ background: transparent; }}

/* ---- sidebar ---- */
#Sidebar {{
    background: {BG_ELEVATED};
    border-right: 1px solid {BORDER};
}}
#SidebarTitle {{
    font-size: 15px;
    font-weight: 600;
    padding: 18px 18px 4px 18px;
    color: {TEXT};
}}
#SidebarSubtitle {{
    font-size: 11px;
    color: {TEXT_FAINT};
    padding: 0 18px 16px 18px;
}}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    margin: 2px 10px;
    text-align: left;
    color: {TEXT_DIM};
    font-size: 13px;
}}
QPushButton#NavButton:hover {{ background: {BG_HOVER}; color: {TEXT}; }}
QPushButton#NavButton:checked {{
    background: {BG_CARD};
    color: {TEXT};
    font-weight: 600;
}}

/* ---- headings ---- */
#PageTitle {{ font-size: 20px; font-weight: 600; }}
#PageSubtitle {{ font-size: 12px; color: {TEXT_DIM}; }}
#SectionLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {TEXT_FAINT};
    letter-spacing: 0.6px;
}}

/* ---- cards ---- */
#Card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
#Card:hover {{ border-color: #3a4256; }}
#CardTitle {{ font-size: 14px; font-weight: 600; }}
#CardMeta {{ font-size: 11px; color: {TEXT_DIM}; }}
#CardNote {{ font-size: 11px; color: {TEXT_FAINT}; }}

/* ---- buttons ---- */
QPushButton {{
    background: {BG_HOVER};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #303748; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: {BG_ELEVATED}; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: none;
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: #2f3646; color: {TEXT_FAINT}; }}

QPushButton#Danger {{ background: transparent; border: 1px solid {DANGER}; color: {DANGER}; }}
QPushButton#Danger:hover {{ background: rgba(239, 95, 95, 0.12); }}

/* ---- inputs ---- */
QLineEdit {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 8px 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}

/* ---- scroll ---- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: #333a4b; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #414a5e; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- log ---- */
QPlainTextEdit#Log {{
    background: #0d0f14;
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 11px;
    color: {TEXT_DIM};
}}

/* ---- misc ---- */
QProgressBar {{
    background: {BG_ELEVATED};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QToolTip {{
    background: {BG_CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
    border-radius: 6px;
}}
"""
