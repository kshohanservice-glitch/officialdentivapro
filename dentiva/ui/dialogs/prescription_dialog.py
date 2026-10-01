"""Prescription dialog — new/view/edit prescription with finalize/print."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from dentiva.core.errors import DentivaError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Dentist
from dentiva.services import prescription_service
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.widgets.prescription_editor import PrescriptionEditor

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from dentiva.core.permissions import Principal


class PrescriptionDialog(QDialog):
    def __init__(
        self,
        session_factory: sessionmaker,
        principal: Principal,
        *,
        prescription=None,
        patient_id: int | None = None,
        visit_id: int | None = None,
        dentist_id: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self._prescription = prescription
        self._patient_id = patient_id
        self._visit_id = visit_id
        self._rx_id: int | None = prescription.id if prescription else None

        self.setWindowTitle("Prescription" if prescription else "New prescription")
        self.setMinimumSize(860, 640)
        self.setModal(True)

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        header.setSpacing(Spacing.S2)
        title = QLabel(self.windowTitle(), self)
        title.setObjectName("DpPageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._dentist_label = QLabel("", self)
        header.addWidget(self._dentist_label)
        root.addLayout(header)

        self._editor = PrescriptionEditor(self)
        root.addWidget(self._editor, 1)

        self._error = QLabel("", self)
        self._error.setObjectName("DpFieldError")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self._finalize_btn = QPushButton("Finalize & Close", self)
        self._finalize_btn.setProperty("variant", "primary")
        self._finalize_btn.clicked.connect(self._finalize)
        self._print_btn = QPushButton("Print…", self)
        self._print_btn.clicked.connect(self._print)
        self._print_btn.setEnabled(False)
        self._close_btn = QPushButton("Save Draft", self)
        self._close_btn.setProperty("variant", "primary-subtle")
        self._close_btn.clicked.connect(self._save_draft_and_close)
        self._cancel_btn = QPushButton("Cancel", self)
        self._cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self._cancel_btn)
        btns.addWidget(self._print_btn)
        btns.addWidget(self._finalize_btn)
        btns.addWidget(self._close_btn)
        root.addLayout(btns)

        self._load_templates()

        if prescription is not None:
            dname = prescription.dentist_name
            if dname and dname != "—":
                self._dentist_label.setText(f"<i>Dentist: {dname}</i>")
            self._editor.load(prescription)
            self._print_btn.setEnabled(prescription.finalized)
            can_edit = (not prescription.finalized) and self._principal.has(Permission.PRESCRIPTIONS_EDIT)
            self._finalize_btn.setEnabled(can_edit)
        else:
            self._editor.load(None)
            if dentist_id is not None:
                with UnitOfWork(self._session_factory) as uow:
                    d_obj = uow.session.get(Dentist, dentist_id)
                    dname = d_obj.name if d_obj else ""
                if dname:
                    self._dentist_label.setText(f"<i>Dentist: {dname}</i>")

    def _load_templates(self) -> None:
        grouped: dict[str, list[str]] = {"cc": [], "oe": [], "advice": []}
        with UnitOfWork(self._session_factory) as uow:
            for opt in prescription_service.list_template_options(uow.session):
                grouped.setdefault(opt.section_key, []).append(opt.display_text)
        self._editor.set_templates(grouped)

    # ------------------------------------------------------------------ save
    def _save_draft_and_close(self) -> None:
        if self._editor.is_finalized():
            self.accept()
            return
        try:
            self._save(finalize=False)
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self.accept()

    def _finalize(self) -> None:
        try:
            rx = self._save(finalize=True)
            if rx is not None:
                self._rx_id = rx.id
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self.accept()

    def _save(self, *, finalize: bool):
        data = prescription_service.PrescriptionInput(
            visit_id=self._visit_id,
            patient_id=self._patient_id,
            chief_complaint=self._editor.chief_complaint(),
            on_examination=self._editor.on_examination(),
            advice=self._editor.advice(),
            notes=self._editor.notes(),
            medicines=self._editor.collect_medicines(),
        )
        with UnitOfWork(self._session_factory) as uow:
            if self._rx_id is None:
                rx = prescription_service.create_prescription(uow.session, self._principal, data)
                uow.commit()
                self._rx_id = rx.id
            else:
                rx = prescription_service.update_prescription(uow.session, self._principal, self._rx_id, data)
                uow.commit()
            if finalize and not rx.finalized:
                rx = prescription_service.finalize_prescription(uow.session, self._principal, rx.id)
                uow.commit()
            return rx

    def _print(self) -> None:
        if self._rx_id is None:
            QMessageBox.information(self, "Print", "Save the prescription first before printing.")
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                rx_row = prescription_service.get_prescription(uow.session, self._principal, self._rx_id)
                if not rx_row.finalized:
                    if QMessageBox.question(
                        self, "Finalize first?",
                        "This prescription is still a draft. Finalize before printing?",
                        QMessageBox.Yes | QMessageBox.No,
                    ) == QMessageBox.Yes:
                        prescription_service.finalize_prescription(uow.session, self._principal, rx_row.id)
                        uow.commit()
                        rx_row = prescription_service.get_prescription(uow.session, self._principal, self._rx_id)
                        self._editor.set_finalized(True)
                    else:
                        return
                from dentiva.printing.builders import build_prescription_doc
                doc = build_prescription_doc(uow.session, rx_row, paper="a4")
            from dentiva.printing.manager import preview_document
            preview_document(self, doc, paper_code="a4")
        except DentivaError as e:
            QMessageBox.warning(self, "Print", e.user_message)
