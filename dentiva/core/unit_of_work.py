"""Unit of Work wrapper around a SQLAlchemy session.

Each service method that writes takes a :class:`UnitOfWork` and calls
``uow.commit()`` on success — or lets the context manager roll back on
exception::

    with UnitOfWork(session_factory) as uow:
        ... work on uow.session ...
        uow.commit()

The session is always closed on exit.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker


class UnitOfWork:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._factory = session_factory
        self.session: Session = None  # type: ignore[assignment]
        self._committed = False

    def __enter__(self) -> UnitOfWork:
        self.session = self._factory()
        self._committed = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None or not self._committed:
                self.session.rollback()
            else:
                self.session.close()
                return
        finally:
            self.session.close()

    def commit(self) -> None:
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        self.session.rollback()


@contextmanager
def session_scope(session_factory: sessionmaker) -> Iterator[Session]:
    """Lightweight session context manager for read-only / internal use."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
