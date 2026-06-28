"""Product ORM model."""

from __future__ import annotations

import uuid

from app.models.base import Base
from sqlalchemy import Column, DateTime, Numeric, String, Text
from sqlalchemy.sql import func


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Product {self.name}>"
