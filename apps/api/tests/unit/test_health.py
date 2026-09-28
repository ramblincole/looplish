from fastapi.testclient import TestClient

from looplish_api.main import create_app


def test_live_health_is_available() -> None:
    response = TestClient(create_app()).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
