"""Prescription editor widget — used inside the visit dialog and as a standalone popup.

Editor includes:
  - Chief complaint / On examination / Advice multi-line fields with quick-pick chips
  - Multi-row medicine table: #, Name, Form, Strength, morning/noon/night checkboxes,
    Meal relation (before/after/with/none), Duration days, Quantity, Instructions.
  - Add / Remove row buttons.
  - Finalize button (locks the Rx) + status indicator.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from dentiva.ui.design_tokens import Spacing

if TYPE_CHECKING:
    from dentiva.services.prescription_service import MedicineLine, PrescriptionRow

FORMS = ["tablet", "capsule", "syrup", "injection", "cream", "ointment", "gel", "mouthwash", "drop", "inhaler", "other"]
MEAL_OPTIONS = ["after", "before", "with", "none"]


class _ChipBar(QWidget):
    """Horizontal row of clickable quick-pick chips."""

    picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(Spacing.S1)

    def set_items(self, items: list[str]) -> None:
        while self._layout.count():
            w = self._layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for text in items:
            b = QPushButton(text, self)
            b.setProperty("variant", "chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=text: self.picked.emit(t))
            self._layout.addWidget(b)
        self._layout.addStretch(1)


class PrescriptionEditor(QWidget):
    """Edit a single prescription draft."""

    finalized_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_finalized = False
        self._template_options: dict[str, list[str]] = {"cc": [], "oe": [], "advice": []}
        root = QVBoxLayout(self)
        root.setSpacing(Spacing.S4)

        # --- clinical notes ---
        notes_box = QGroupBox("Clinical notes", self)
        nf = QHBoxLayout() if False else None
        from PySide6.QtWidgets import QFormLayout
        nf = QFormLayout(notes_box)
        nf.setLabelAlignment(Qt.AlignTop | Qt.AlignRight)

        self._cc = QPlainTextEdit(notes_box)
        self._cc.setFixedHeight(60)
        self._cc.setPlaceholderText("Chief complaint: why is the patient here today?")
        self._cc_chips = _ChipBar(notes_box)
        self._cc_chips.picked.connect(lambda t: self._append_text(self._cc, t))

        self._oe = QPlainTextEdit(notes_box)
        self._oe.setFixedHeight(60)
        self._oe.setPlaceholderText("On examination: findings from your assessment.")
        self._oe_chips = _ChipBar(notes_box)
        self._oe_chips.picked.connect(lambda t: self._append_text(self._oe, t))

        self._adv = QPlainTextEdit(notes_box)
        self._adv.setFixedHeight(60)
        self._adv.setPlaceholderText("Advice / home-care instructions.")
        self._adv_chips = _ChipBar(notes_box)
        self._adv_chips.picked.connect(lambda t: self._append_text(self._adv, t))

        self._rx_notes = QPlainTextEdit(notes_box)
        self._rx_notes.setFixedHeight(40)
        self._rx_notes.setPlaceholderText("Internal notes (not printed on Rx).")

        cc_wrap = QWidget(notes_box)
        cc_l = QVBoxLayout(cc_wrap)
        cc_l.setContentsMargins(0, 0, 0, 0)
        cc_l.setSpacing(Spacing.S1)
        cc_l.addWidget(self._cc)
        cc_l.addWidget(self._cc_chips)
        nf.addRow("CC", cc_wrap)

        oe_wrap = QWidget(notes_box)
        oe_l = QVBoxLayout(oe_wrap)
        oe_l.setContentsMargins(0, 0, 0, 0)
        oe_l.setSpacing(Spacing.S1)
        oe_l.addWidget(self._oe)
        oe_l.addWidget(self._oe_chips)
        nf.addRow("O/E", oe_wrap)

        adv_wrap = QWidget(notes_box)
        adv_l = QVBoxLayout(adv_wrap)
        adv_l.setContentsMargins(0, 0, 0, 0)
        adv_l.setSpacing(Spacing.S1)
        adv_l.addWidget(self._adv)
        adv_l.addWidget(self._adv_chips)
        nf.addRow("Advice", adv_wrap)
        nf.addRow("Notes", self._rx_notes)
        root.addWidget(notes_box)

        # --- medicines table ---
        meds_box = QGroupBox("Medicines", self)
        ml = QVBoxLayout(meds_box)
        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._add_btn = QPushButton("+ Add medicine", meds_box)
        self._add_btn.setProperty("variant", "primary")
        self._add_btn.clicked.connect(self.add_empty_row)
        bar.addWidget(self._add_btn)
        bar.addStretch(1)
        self._final_status = QLabel("Draft", meds_box)
        self._final_status.setStyleSheet("color:#B54708; font-weight:600;")
        bar.addWidget(self._final_status)
        ml.addLayout(bar)

        self._table = QTableWidget(0, 11, meds_box)
        self._table.setObjectName("DpDataTable")
        self._table.setHorizontalHeaderLabels([
            "#", "Name", "Form", "Strength", "Morn", "Noon", "Night",
            "Meal", "Days", "Qty", "Instructions",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self._table.horizontalHeader()
        resize_modes = [
            QHeaderView.ResizeToContents,
            QHeaderView.Stretch,
            QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents,
            QHeaderView.Stretch,
        ]
        for col, mode in enumerate(resize_modes):
            hh.setSectionResizeMode(col, mode)
        ml.addWidget(self._table, 1)
        root.addWidget(meds_box, 1)

        self.add_empty_row()

    # ------------------------------------------------------------------ API
    def set_templates(self, templates: dict[str, list[str]]) -> None:
        self._template_options = templates
        self._cc_chips.set_items(templates.get("cc", []))
        self._oe_chips.set_items(templates.get("oe", []))
        self._adv_chips.set_items(templates.get("advice", []))

    def load(self, rx: PrescriptionRow | None = None) -> None:
        self._cc.setPlainText("")
        self._oe.setPlainText("")
        self._adv.setPlainText("")
        self._rx_notes.setPlainText("")
        self._table.setRowCount(0)
        if rx is None:
            self.add_empty_row()
            self.set_finalized(False)
            return
        self._cc.setPlainText(rx.chief_complaint)
        self._oe.setPlainText(rx.on_examination)
        self._adv.setPlainText(rx.advice)
        self._rx_notes.setPlainText(rx.notes)
        if not rx.medicines:
            self.add_empty_row()
        else:
            for m in rx.medicines:
                self._add_row(m)
        self.set_finalized(rx.finalized)

    def collect_medicines(self) -> list[MedicineLine]:
        from dentiva.services.prescription_service import MedicineLine
        meds: list[MedicineLine] = []
        for row in range(self._table.rowCount()):
            name_w = self._table.cellWidget(row, 1)
            name = name_w.text().strip() if isinstance(name_w, QLineEdit) else ""
            if not name:
                continue
            form_cb = self._table.cellWidget(row, 2)
            form = form_cb.currentText() if isinstance(form_cb, QComboBox) else ""
            str_w = self._table.cellWidget(row, 3)
            strength = str_w.text().strip() if isinstance(str_w, QLineEdit) else ""
            morn_w = self._table.cellWidget(row, 4)
            morn = isinstance(morn_w, QCheckBox) and morn_w.isChecked()
            noon_w = self._table.cellWidget(row, 5)
            noon = isinstance(noon_w, QCheckBox) and noon_w.isChecked()
            night_w = self._table.cellWidget(row, 6)
            night = isinstance(night_w, QCheckBox) and night_w.isChecked()
            meal_cb = self._table.cellWidget(row, 7)
            meal = meal_cb.currentText() if isinstance(meal_cb, QComboBox) else "after"
            days_w = self._table.cellWidget(row, 8)
            days = int(days_w.value()) if isinstance(days_w, QSpinBox) else 0
            qty_w = self._table.cellWidget(row, 9)
            qty = qty_w.text().strip() if isinstance(qty_w, QLineEdit) else ""
            inst_w = self._table.cellWidget(row, 10)
            inst = inst_w.text().strip() if isinstance(inst_w, QLineEdit) else ""
            meds.append(
                MedicineLine(
                    idx=row, name=name, form=form, strength=strength,
                    frequency_morning=morn, frequency_noon=noon, frequency_night=night,
                    meal_relation=meal, duration_days=days, quantity=qty, instructions=inst,
                )
            )
        return meds

    def chief_complaint(self) -> str:
        return self._cc.toPlainText().strip()

    def on_examination(self) -> str:
        return self._oe.toPlainText().strip()

    def advice(self) -> str:
        return self._adv.toPlainText().strip()

    def notes(self) -> str:
        return self._rx_notes.toPlainText().strip()

    def set_finalized(self, finalized: bool) -> None:
        self._is_finalized = finalized
        self._cc.setReadOnly(finalized)
        self._oe.setReadOnly(finalized)
        self._adv.setReadOnly(finalized)
        self._rx_notes.setReadOnly(finalized)
        self._add_btn.setEnabled(not finalized)
        for row in range(self._table.rowCount()):
            for col in range(1, 11):
                w = self._table.cellWidget(row, col)
                if w is not None:
                    w.setEnabled(not finalized)
            del_btn = self._table.cellWidget(row, 0)
            if isinstance(del_btn, QPushButton):
                del_btn.setEnabled(not finalized)
        if finalized:
            self._final_status.setText("✓ Finalized")
            self._final_status.setStyleSheet("color:#027A48; font-weight:600;")
        else:
            self._final_status.setText("Draft")
            self._final_status.setStyleSheet("color:#B54708; font-weight:600;")
        self.finalized_changed.emit(finalized)

    def is_finalized(self) -> bool:
        return self._is_finalized

    # ---------------------------------------------------------------- rows
    def add_empty_row(self) -> None:
        self._add_row(None)

    def _add_row(self, m: MedicineLine | None) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        # # column: remove button + row number
        del_btn = QPushButton("✕", self._table)
        del_btn.setFixedWidth(28)
        del_btn.setProperty("variant", "danger-text")
        del_btn.clicked.connect(lambda _=False, row=r: self._remove_row(row))
        num_wrap = QWidget(self._table)
        nw = QHBoxLayout(num_wrap)
        nw.setContentsMargins(Spacing.S1, 0, Spacing.S1, 0)
        nw.setSpacing(Spacing.S1)
        lbl = QLabel(str(r + 1), num_wrap)
        nw.addWidget(lbl)
        nw.addWidget(del_btn)
        self._table.setCellWidget(r, 0, num_wrap)

        name = QLineEdit(self._table)
        name.setPlaceholderText("e.g. Amoxicillin")
        if m:
            name.setText(m.name)
        self._table.setCellWidget(r, 1, name)

        form = QComboBox(self._table)
        form.addItems(FORMS)
        if m and m.form in FORMS:
            form.setCurrentText(m.form)
        self._table.setCellWidget(r, 2, form)

        strength = QLineEdit(self._table)
        strength.setPlaceholderText("500 mg")
        if m:
            strength.setText(m.strength)
        self._table.setCellWidget(r, 3, strength)

        def _cb(checked: bool) -> QCheckBox:
            b = QCheckBox(self._table)
            b.setChecked(checked)
            return b

        self._table.setCellWidget(r, 4, _cb(m.frequency_morning if m else False))
        self._table.setCellWidget(r, 5, _cb(m.frequency_noon if m else False))
        self._table.setCellWidget(r, 6, _cb(m.frequency_night if m else True))

        meal = QComboBox(self._table)
        meal.addItems(MEAL_OPTIONS)
        if m and m.meal_relation in MEAL_OPTIONS:
            meal.setCurrentText(m.meal_relation)
        self._table.setCellWidget(r, 7, meal)

        days = QSpinBox(self._table)
        days.setRange(0, 365)
        days.setSuffix(" d")
        if m:
            days.setValue(int(m.duration_days or 0))
        else:
            days.setValue(3)
        self._table.setCellWidget(r, 8, days)

        qty = QLineEdit(self._table)
        qty.setPlaceholderText("1 strip")
        if m:
            qty.setText(m.quantity)
        self._table.setCellWidget(r, 9, qty)

        inst = QLineEdit(self._table)
        inst.setPlaceholderText("e.g. If pain persists")
        if m:
            inst.setText(m.instructions)
        self._table.setCellWidget(r, 10, inst)

        self._table.setRowHeight(r, 36)
        if self._is_finalized:
            for col in range(1, 11):
                w = self._table.cellWidget(r, col)
                if w is not None:
                    w.setEnabled(False)
            del_btn.setEnabled(False)

    def _remove_row(self, row: int) -> None:
        self._table.removeRow(row)
        if self._table.rowCount() == 0:
            self.add_empty_row()
        # renumber
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, 0)
            if w is None:
                continue
            labels = list(w.findChildren(QLabel))
            if labels:
                labels[0].setText(str(r + 1))

    def _append_text(self, widget: QPlainTextEdit, chip: str) -> None:
        cur = widget.toPlainText().strip()
        if chip.lower() in cur.lower():
            return
        if cur:
            widget.setPlainText(cur + "\n• " + chip)
        else:
            widget.setPlainText("• " + chip)
