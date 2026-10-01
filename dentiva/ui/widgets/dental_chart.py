"""Interactive FDI dental chart widget.

Renders adult (permanent) or pediatric (deciduous) teeth arranged by
quadrant. Each tooth is a clickable ellipse/rounded rectangle; colors
reflect the current/historic finding and clicking a tooth while a finding
is selected in the palette marks that tooth with the finding.

The widget operates on a dict ``{tooth_code: finding_code}`` exposing
``get_state()/set_state()`` and emits ``tooth_clicked(tooth_code)`` so the
host dialog/view can persist changes.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dentiva.services.visit_service import (
    FINDING_CODE_TO_COLOR,
    FINDING_CODE_TO_LABEL,
    FINDINGS,
    ada_equivalent,
)

TOOTH_SIZE = 40
TOOTH_GAP = 8
QUADRANT_GAP = 30
PALETTE_BTN_SIZE = 36

# FDI quadrant ordering for rendering: upper-right, upper-left, lower-right, lower-left.
# Each entry maps to (label, teeth_list, x_direction: +1 for right-midline-to-far, -1 for far-to-midline).
ADULT_QUADRANTS: tuple[tuple[int, str, tuple[int, ...], bool], ...] = (
    (2, "Upper Left (Q2)",  tuple(range(1, 9)), False),  # 28..21 going midline outward; we iterate 1-8 but reverse x position
    (1, "Upper Right (Q1)", tuple(range(8, 0, -1)), True),
    (4, "Lower Right (Q4)", tuple(range(8, 0, -1)), True),
    (3, "Lower Left (Q3)",  tuple(range(1, 9)), False),
)
PEDIATRIC_QUADRANTS: tuple[tuple[int, str, tuple[int, ...], bool], ...] = (
    (6, "Upper Left (Q6)",  tuple(range(1, 6)), False),
    (5, "Upper Right (Q5)", tuple(range(5, 0, -1)), True),
    (8, "Lower Right (Q8)", tuple(range(5, 0, -1)), True),
    (7, "Lower Left (Q7)",  tuple(range(1, 6)), False),
)


@dataclass
class _ToothItem:
    code: str
    label: str
    is_upper: bool
    color_key: str


class DentalChartWidget(QWidget):
    """Interactive FDI dental chart."""

    tooth_clicked = Signal(str)  # tooth_code
    finding_changed = Signal(str, str)  # tooth_code, finding_code

    def __init__(self, *, pediatric: bool = False, editable: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._pediatric = pediatric
        self._editable = editable
        self._state: dict[str, str] = {}  # tooth_code -> finding_code
        self._selected_finding: str = "caries" if editable else ""
        self._teeth: dict[str, _ToothItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Palette row
        self._palette_row = QHBoxLayout()
        self._palette_row.setSpacing(6)
        self._palette_group = QButtonGroup(self)
        self._palette_group.setExclusive(True)
        for code, label, color in FINDINGS:
            btn = QToolButton(self)
            btn.setCheckable(True)
            btn.setFixedSize(PALETTE_BTN_SIZE + 12, PALETTE_BTN_SIZE + 8)
            btn.setToolTip(f"{label} ({code})")
            # Use a colored square + label via stylesheet.
            btn.setStyleSheet(
                f"QToolButton {{ border: 2px solid transparent; border-radius: 6px; padding: 2px; }}"
                f"QToolButton:checked {{ border: 2px solid {color}; background-color: {color}33; }}"
            )
            swatch = QLabel(self._swatch_html(color, label), btn)
            swatch.setAlignment(Qt.AlignCenter)
            btn.clicked.connect(lambda _=False, c=code: self._set_selected_finding(c))
            self._palette_group.addButton(btn)
            self._palette_row.addWidget(btn)
            if code == "caries":
                btn.setChecked(True)
        self._palette_row.addStretch(1)
        hint = QLabel("Click a tooth to mark it with the selected finding. Click 'Healthy' to clear.", self)
        hint.setStyleSheet("color:#667085;")
        hint.setWordWrap(True)
        self._palette_row.addWidget(hint, 2)
        root.addLayout(self._palette_row)

        if not editable:
            # Hide palette & hint when read-only (historical view)
            for i in range(self._palette_row.count()):
                item = self._palette_row.itemAt(i)
                if item is not None and item.widget() is not None:
                    item.widget().setEnabled(False)

        # Canvas
        self._scene = QGraphicsScene(self)
        self._view = _ChartView(self._scene, self)
        self._view.setRenderHint(QPainter.Antialiasing)
        self._view.setFrameShape(QFrame.NoFrame)
        self._view.setRenderHint(QPainter.TextAntialiasing)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._view.setMinimumHeight(420 if not pediatric else 360)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self._view, 1)

        self._build_chart()

    # ----------------------------------------------------------------- API
    def set_editable(self, editable: bool) -> None:
        self._editable = editable

    def set_state(self, state: dict[str, str]) -> None:
        self._state = dict(state)
        self._update_colors()

    def get_state(self) -> dict[str, str]:
        return dict(self._state)

    def selected_finding(self) -> str:
        return self._selected_finding

    # -------------------------------------------------------------- palette
    def _set_selected_finding(self, code: str) -> None:
        self._selected_finding = code

    def _swatch_html(self, color: str, label: str) -> str:
        # Mini HTML snippet for the tool button: a colored square then label.
        return f"<div style='display:flex;align-items:center;gap:4px;font-size:10px;'><span style='display:inline-block;width:14px;height:14px;border-radius:3px;background:{color};border:1px solid rgba(0,0,0,0.1);'></span><span>{label}</span></div>"

    # --------------------------------------------------------------- render
    def _build_chart(self) -> None:
        self._scene.clear()
        self._teeth.clear()
        quads = ADULT_QUADRANTS if not self._pediatric else PEDIATRIC_QUADRANTS
        teeth_per_row = 8 if not self._pediatric else 5
        row_width = teeth_per_row * (TOOTH_SIZE + TOOTH_GAP) + QUADRANT_GAP
        # Starting x center point (midline)
        mid_x = row_width / 2
        top_y = 40
        upper_row_y = top_y
        lower_row_y = top_y + (TOOTH_SIZE + TOOTH_GAP) * 2 + 60
        font = QFont()
        font.setPointSize(8)
        for qi, (qnum, label, teeth, mirrored) in enumerate(quads):
            is_upper = qi < 2
            y = upper_row_y if is_upper else lower_row_y
            # Quadrant label
            lbl = self._scene.addText(label, font)
            lbl.setDefaultTextColor(QColor("#667085"))
            if qnum in (1, 5):
                lbl.setPos(mid_x + QUADRANT_GAP / 2 + 8, y - 24)
            else:
                lbl.setPos(mid_x - QUADRANT_GAP / 2 - 130, y - 24)
            for i, tnum in enumerate(teeth):
                offset = (i + 1) * (TOOTH_SIZE + TOOTH_GAP)
                if mirrored:
                    x = mid_x + QUADRANT_GAP / 2 + (i * (TOOTH_SIZE + TOOTH_GAP))
                else:
                    x = mid_x - QUADRANT_GAP / 2 - TOOTH_SIZE - (i * (TOOTH_SIZE + TOOTH_GAP))
                # Y slightly offset for root shape (upper teeth roots up, lower down).
                tooth_rect = QRectF(x, y, TOOTH_SIZE, TOOTH_SIZE)
                code = f"{qnum}{tnum}"
                item = _ToothGraphicsItem(code, self, tooth_rect, is_upper=is_upper)
                self._scene.addItem(item)
                # Label under/beside tooth
                lab = self._scene.addSimpleText(code, font)
                lab.setBrush(QBrush(QColor("#475467")))
                lab.setPos(x + TOOTH_SIZE/2 - 10, y + TOOTH_SIZE + 2)
                ada = ada_equivalent(code)
                if ada and ada != code:
                    ada_lab = self._scene.addSimpleText(ada, font)
                    ada_lab.setBrush(QBrush(QColor("#98A2B3")))
                    ada_lab.setPos(x + TOOTH_SIZE/2 - 10, y + TOOTH_SIZE + 15)
                self._teeth[code] = _ToothItem(code=code, label=code, is_upper=is_upper, color_key="healthy")
        # Midline indicator
        pen = QPen(QColor("#D0D5DD"))
        pen.setStyle(Qt.DashLine)
        self._scene.addLine(mid_x, upper_row_y - 12, mid_x, lower_row_y + TOOTH_SIZE + 24, pen)
        # Set scene rect
        self._scene.setSceneRect(0, 0, row_width, lower_row_y + TOOTH_SIZE + 60)
        self._view.fit_scene()
        self._update_colors()

    def _update_colors(self) -> None:
        for code, item in self._teeth.items():
            finding = self._state.get(code, "healthy")
            item.color_key = finding
        for it in self._scene.items():
            if isinstance(it, _ToothGraphicsItem):
                it.update_color()

    def _on_tooth_clicked(self, code: str) -> None:
        if not self._editable:
            self.tooth_clicked.emit(code)
            return
        f = self._selected_finding
        if f == "healthy":
            self._state.pop(code, None)
        else:
            self._state[code] = f
        self._update_colors()
        self.finding_changed.emit(code, f)
        self.tooth_clicked.emit(code)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        QWidget.resizeEvent(self, event)
        self._view.fit_scene()


class _ToothGraphicsItem(QGraphicsEllipseItem):
    """A single tooth rendered as a rounded ellipse."""

    def __init__(self, code: str, chart: DentalChartWidget, rect: QRectF, *, is_upper: bool) -> None:
        super().__init__(rect)
        self._code = code
        self._chart = chart
        self._is_upper = is_upper
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(QColor("#98A2B3"), 1.2))
        self.setBrush(QBrush(QColor("#F2F4F7")))
        self.setZValue(1)

    def update_color(self) -> None:
        finding = self._chart._state.get(self._code, "healthy")
        color = FINDING_CODE_TO_COLOR.get(finding, "#F2F4F7")
        self.setBrush(QBrush(QColor(color)))
        if finding == "healthy":
            self.setPen(QPen(QColor("#98A2B3"), 1.2))
        else:
            self.setPen(QPen(QColor("#344054"), 1.0))
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._chart._on_tooth_clicked(self._code)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event) -> None:  # type: ignore[override]
        self.setPen(QPen(QColor("#1F5AA6"), 2.0))
        self.setToolTip(f"{self._code} — {FINDING_CODE_TO_LABEL.get(self._chart._state.get(self._code, 'healthy'), 'Healthy')}")
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        self.update_color()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None) -> None:  # type: ignore[override]
        # Draw a tooth-like rounded shape rather than a plain ellipse.
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        r = self.rect()
        # Rounded rectangle with a "root" tail pointing up/down.
        painter.drawRoundedRect(r, 8, 8)
        # Crown midline indicator
        painter.setPen(QPen(QColor(0, 0, 0, 30), 1))
        mid_y = r.y() + (r.height() / 2 if self._is_upper else r.height() / 2)
        # Slight midline on crown
        painter.drawLine(QPointF(r.x() + 6, r.y() + r.height() * 0.45),
                         QPointF(r.right() - 6, r.y() + r.height() * 0.45))


class _ChartView(QGraphicsView):
    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#FFFFFF")))

    def fit_scene(self) -> None:
        if self.scene() is None:
            return
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.fit_scene()


