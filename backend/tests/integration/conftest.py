"""Integration tests run against a migrated + seeded PostgreSQL (see Makefile `db-up`, `migrate`, `seed`)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

from app.db.session import app_engine
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[httpx.AsyncClient]:
    try:
        async with app_engine().connect() as conn:
            await conn.execute(text("SELECT 1 FROM app.users LIMIT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL not available: {exc!r}")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=30) as c:
        yield c


async def _login(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
async def analyst(client: httpx.AsyncClient) -> dict[str, str]:
    return await _login(client, "analyst@demo.local", "Analyst@123")


@pytest.fixture(scope="session")
async def admin(client: httpx.AsyncClient) -> dict[str, str]:
    return await _login(client, "admin@demo.local", "Admin@123")


@pytest.fixture
async def conversation(client: httpx.AsyncClient, analyst: dict[str, str]) -> int:
    r = await client.post("/conversations", json={}, headers=analyst)
    return int(r.json()["id"])
