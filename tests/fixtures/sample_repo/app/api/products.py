"""Product API."""

from __future__ import annotations

from app.schemas.product import ProductCreate, ProductResponse
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/", response_model=list[ProductResponse])
async def list_products():
    """List all products."""
    return []


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    """Get a single product."""
    raise HTTPException(404, "not implemented")


@router.post("/", response_model=ProductResponse)
async def create_product(body: ProductCreate):
    """Create a product."""
    raise HTTPException(501, "not implemented")
