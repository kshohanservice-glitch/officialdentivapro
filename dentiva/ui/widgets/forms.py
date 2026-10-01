"""Reusable form primitives: labelled inputs, file pickers, error display."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dentiva.ui.design_tokens import Spacing


class FormRow(QWidget):
    """Vertical label + input + optional hint/error row."""

    def __init__(self, label: str, input_widget: QWidget, *,
                 hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.S1)
        lbl = QLabel(label, self)
        lbl.setObjectName("DpFieldLabel")
        layout.addWidget(lbl)
        layout.addWidget(input_widget)
        self._error = QLabel("", self)
        self._error.setObjectName("DpFieldError")
        self._error.setVisible(False)
        layout.addWidget(self._error)
        if hint:
            h = QLabel(hint, self)
            h.setObjectName("DpFieldHint")
            h.setWordWrap(True)
            layout.addWidget(h)
        self._input = input_widget

    def set_error(self, message: str | None) -> None:
        if message:
            self._error.setText(message)
            self._error.setVisible(True)
            self._input.setStyleSheet("border: 1px solid #F04438;")
        else:
            self._error.setText("")
            self._error.setVisible(False)
            self._input.setStyleSheet("")


class FilePickerRow(QWidget):
    """Line edit + Browse button for selecting a file (e.g. logo, signature)."""

    file_selected = Signal(str)

    def __init__(self, label: str, *, parent: QWidget | None = None,
                 filter: str = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)") -> None:
        super().__init__(parent)
        self._filter = filter
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.S1)
        lbl = QLabel(label, self)
        lbl.setObjectName("DpFieldLabel")
        layout.addWidget(lbl)
        row = QHBoxLayout()
        row.setSpacing(Spacing.S2)
        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("No file selected")
        self._edit.setReadOnly(True)
        self._browse = QPushButton("Browse…", self)
        self._browse.clicked.connect(self._pick)
        self._clear = QPushButton("Clear", self)
        self._clear.clicked.connect(self._reset)
        row.addWidget(self._edit, 1)
        row.addWidget(self._browse)
        row.addWidget(self._clear)
        layout.addLayout(row)
        self._error = QLabel("", self)
        self._error.setObjectName("DpFieldError")
        self._error.setVisible(False)
        layout.addWidget(self._error)
        self._path: str = ""

    def _pick(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(self, "Select file", "", self._filter)
        if fname:
            self.set_path(fname)

    def _reset(self) -> None:
        self._path = ""
        self._edit.setText("")
        self.file_selected.emit("")

    def set_path(self, path: str) -> None:
        self._path = path
        self._edit.setText(path)
        self.file_selected.emit(path)

    def path(self) -> str:
        return self._path

    def set_error(self, message: str | None) -> None:
        if message:
            self._error.setText(message)
            self._error.setVisible(True)
        else:
            self._error.setText("")
            self._error.setVisible(False)


def set_text(widget: QWidget, value: str) -> None:
    """Set text on any text-like widget (QLineEdit/QTextEdit/QLabel)."""
    if isinstance(widget, QTextEdit):
        widget.setPlainText(value or "")
    elif isinstance(widget, QLineEdit):
        widget.setText(value or "")
