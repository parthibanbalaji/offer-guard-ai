from fastapi import FastAPI
from fastapi.testclient import TestClient


def configure_test_app(monkeypatch) -> tuple[FastAPI, object]:
    monkeypatch.setenv(
        "OFFERGUARD_DATABASE_URL",
        "postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    from app.main import app

    resources = object()

    def create_app_resources(_) -> object:
        return resources

    async def check_startup_dependencies(_, checked_resources: object) -> None:
        assert checked_resources is resources

    async def close_app_resources(closed_resources: object) -> None:
        assert closed_resources is resources
        return None

    monkeypatch.setattr("app.main.create_app_resources", create_app_resources)
    monkeypatch.setattr("app.main.check_startup_dependencies", check_startup_dependencies)
    monkeypatch.setattr("app.main.close_app_resources", close_app_resources)

    return app, resources


def test_health_and_ready_endpoints(monkeypatch) -> None:
    app, resources = configure_test_app(monkeypatch)

    async def check_runtime_dependencies(checked_resources: object) -> None:
        assert checked_resources is resources

    monkeypatch.setattr(
        "app.api.v1.routes.health.check_runtime_dependencies", check_runtime_dependencies
    )

    with TestClient(app) as client:
        health_response = client.get("/api/v1/health")
        ready_response = client.get("/api/v1/ready")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok", "version": "0.1.0"}
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ok", "version": "0.1.0"}


def test_ready_endpoint_returns_503_when_dependencies_are_down(monkeypatch) -> None:
    app, _ = configure_test_app(monkeypatch)

    async def check_runtime_dependencies(_: object) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(
        "app.api.v1.routes.health.check_runtime_dependencies", check_runtime_dependencies
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "dependencies are not ready"}
