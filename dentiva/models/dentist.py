"""Dentist and designation models."""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dentiva.db.base import Base, SoftDeleteMixin, TimestampMixin

dentist_designations = Table(
    "dentist_designations",
    Base.metadata,
    Column("dentist_id", ForeignKey("dentist.id", ondelete="CASCADE"), primary_key=True),
    Column("designation_id", ForeignKey("designation.id", ondelete="CASCADE"), primary_key=True),
)


class Designation(Base, TimestampMixin):
    __tablename__ = "designation"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)  # e.g. BDS, FCPS, DDS
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")


class Dentist(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "dentist"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    qualifications: Mapped[str] = mapped_column(Text, default="", server_default="")
    certifications: Mapped[str] = mapped_column(Text, default="", server_default="")
    registration_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(50), default="", server_default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    signature_path: Mapped[str] = mapped_column(String(500), default="", server_default="")
    photo_path: Mapped[str] = mapped_column(String(500), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")

    designations: Mapped[list[Designation]] = relationship(
        secondary=dentist_designations, lazy="selectin"
    )
