"""Employee/staff records (separate from login users)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, SoftDeleteMixin, TimestampMixin


class Staff(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str] = mapped_column(String(120), default="", server_default="")
    dob: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str] = mapped_column(String(20), default="", server_default="")
    blood_group: Mapped[str] = mapped_column(String(10), default="", server_default="")
    address: Mapped[str] = mapped_column(Text, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(50), default="", server_default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    nid: Mapped[str] = mapped_column(String(50), default="", server_default="")
    photo_path: Mapped[str] = mapped_column(String(500), default="", server_default="")
    salary_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    joining_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    employment_status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
