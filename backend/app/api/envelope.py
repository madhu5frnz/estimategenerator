from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from app.core.request_id import current_request_id

T = TypeVar("T")


class Meta(BaseModel):
    request_id: str | None = None


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: Meta


def ok(data: T) -> Envelope[T]:
    return Envelope[T](data=data, meta=Meta(request_id=current_request_id()))
