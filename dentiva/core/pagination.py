"""Pagination helpers for list views / API-style queries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 500


@dataclass
class Page(Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def clamp_page(page: int | None, page_size: int | None) -> tuple[int, int]:
    p = max(1, int(page or 1))
    ps = max(1, min(MAX_PAGE_SIZE, int(page_size or DEFAULT_PAGE_SIZE)))
    return p, ps


def page_offset(page: int, page_size: int) -> int:
    return (page - 1) * page_size
