"""Test for product API."""

from fastapi.testclient import TestClient


def test_list_products_returns_empty(client: TestClient):
    resp = client.get("/products/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_product_not_found(client: TestClient):
    resp = client.get("/products/nonexistent")
    assert resp.status_code == 404
