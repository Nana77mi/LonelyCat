import asyncio

from app.main import health


def test_health_endpoint():
    response = asyncio.run(health())
    assert response == {"status": "ok"}
