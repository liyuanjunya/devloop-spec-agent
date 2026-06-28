"""User ORM model."""

from __future__ import annotations

import uuid

from app.models.base import Base
from sqlalchemy import Column, DateTime, String
from sqlalchemy.sql import func


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False)
    username = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<User {self.username}>"
