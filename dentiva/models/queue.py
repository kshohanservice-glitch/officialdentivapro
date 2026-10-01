"""Queue entries."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.core.dates import TZ
from dentiva.db.base import Base, TimestampMixin


class QueueEntry(Base, TimestampMixin):
    __tablename__ = "queue_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="CASCADE"), nullable=False, index=True)
    dentist_id: Mapped[int | None] = mapped_column(ForeignKey("dentist.id", ondelete="SET NULL"), nullable=True, index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointment.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="waiting", server_default="waiting", index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    arrived_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None), nullable=False
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
