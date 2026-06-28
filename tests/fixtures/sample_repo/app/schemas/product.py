"""Product schemas (pydantic v2)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, constr


class ProductCreate(BaseModel):
    name: constr(min_length=1, max_length=200)
    description: str | None = None
    price: Decimal = Field(..., ge=0)


class ProductResponse(BaseModel):
    id: str
    name: str
    description: str | None
    price: Decimal
