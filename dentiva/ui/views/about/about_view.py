# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""About Dentiva Pro page."""
from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from dentiva.__version__ import __version__
except Exception:  # pragma: no cover
    __version__ = "1.0.0"


class AboutView(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title = QLabel("Dentiva Pro", self)
        title.setObjectName("DpPageTitle")
        f = title.font()
        f.setPointSize(f.pointSize() + 8)
        f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        sub = QLabel(
            f"Version {__version__} · Fully offline dental clinic management",
            self,
        )
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(sub)

        info = QLabel(
            "<p>Dentiva Pro is a commercially distributable, fully offline "
            "Windows desktop clinic management application for dental "
            "practices in Bangladesh. All data is stored locally in an "
            "encrypted-at-rest SQLite database; no cloud, telemetry, or "
            "paid API is required at runtime.</p>"
            "<p><b>Developed by</b><br>Shohan Khan<br>"
            "<a href=\"mailto:helloiamshohan@gmail.com\">helloiamshohan@gmail.com</a></p>"
            "<p><b>Currency</b>: BDT (৳) — money stored as integer paisa.</p>"
            "<p><b>Licenses</b>: PySide6 (LGPLv3), Python/PSF, SQLAlchemy (MIT), "
            "Alembic (MIT), ReportLab (BSD/BSD-like), bcrypt (Apache-2.0), "
            "pydantic (MIT), pytest (MIT), NSIS (zlib).</p>",
            self,
        )
        info.setTextFormat(Qt.RichText)
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        root.addWidget(info, 1)

        env = QLabel(self)
        env.setText(
            f"<small>Python {sys.version.split()[0]} · "
            f"Qt/PySide6 · {platform.system()} {platform.release()}</small>"
        )
        env.setTextFormat(Qt.RichText)
        root.addWidget(env)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Back", self)
        close_btn.clicked.connect(lambda: self.parentWidget() and None)
        root.addLayout(btn_row)

    def refresh(self) -> None:
        pass
