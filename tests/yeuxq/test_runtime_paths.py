from __future__ import annotations

from pathlib import Path

import pytest

from yeuxq.security import RuntimeSecrets
from yeuxq import settings as settings_module
from yeuxq.settings import Settings


@pytest.fixture(autouse=True)
def isolated_settings_cache(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "YEUXQ_CONFIG",
        "YEUXQ_DATA_DIR",
        "YEUXQ_HOST",
        "YEUXQ_PORT",
        "YEUXQ_APP__NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def test_data_dir_environment_has_priority_and_confines_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YEUXQ_DATA_DIR", "runtime")

    settings = settings_module.reload_settings()

    assert settings.app.name == "yeuxQ"
    assert settings.runtime_data_root == (tmp_path / "runtime").resolve()
    assert settings.resolve_data_path("kline.db") == (tmp_path / "runtime" / "kline.db").resolve()
    with pytest.raises(ValueError, match="remain under"):
        settings.resolve_data_path("../outside.db")


def test_explicit_relative_config_prefers_cwd_and_missing_file_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cwd = tmp_path / "cwd"
    project = tmp_path / "project"
    cwd.mkdir()
    project.mkdir()
    relative = Path("config") / "custom.yaml"
    (cwd / relative).parent.mkdir()
    (project / relative).parent.mkdir()
    (cwd / relative).write_text('app:\n  name: "cwd-name"\n', encoding="utf-8")
    (project / relative).write_text('app:\n  name: "project-name"\n', encoding="utf-8")

    resolved = settings_module.resolve_explicit_config(
        relative,
        cwd=cwd,
        project_root=project,
    )
    assert resolved == (cwd / relative).resolve()

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("YEUXQ_CONFIG", str(relative))
    settings = settings_module.reload_settings()
    assert settings.app.name == "cwd-name"
    assert settings.config_path == (cwd / relative).resolve()

    monkeypatch.setenv("YEUXQ_CONFIG", "missing.yaml")
    settings_module.get_settings.cache_clear()
    with pytest.raises(FileNotFoundError, match="YEUXQ_CONFIG"):
        settings_module.get_settings()


def test_default_without_config_uses_model_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YEUXQ_HOST", "localhost")
    monkeypatch.setenv("YEUXQ_PORT", "9911")

    settings = settings_module.reload_settings()

    assert settings.config_path is None
    assert settings.app.name == "yeuxQ"
    assert settings.app.host == "localhost"
    assert settings.app.port == 9911
    assert settings.prediction.horizon_days == 5


def test_wheel_default_data_root_is_outside_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "site-packages" / "yeuxq"
    package_root.mkdir(parents=True)
    local_data = tmp_path / "user-data"
    monkeypatch.setattr(settings_module, "PROJECT_ROOT", None)
    monkeypatch.setenv("LOCALAPPDATA", str(local_data))

    runtime_root = settings_module.default_runtime_data_root()

    assert runtime_root == (local_data / "yeuxQ").resolve()
    assert package_root not in runtime_root.parents


def test_container_writes_only_to_runtime_data_root(tmp_path: Path) -> None:
    from yeuxq.api.deps import init_container, shutdown_container

    package_root = tmp_path / "site-packages" / "yeuxq"
    package_root.mkdir(parents=True)
    runtime_root = tmp_path / "runtime-data"
    settings = Settings(data_dir=runtime_root)

    container = init_container(settings, RuntimeSecrets())

    assert container.store.db_path == (runtime_root / "kline.db").resolve()
    assert container.store.db_path.is_file()
    assert container.report_store.root == (runtime_root / "reports").resolve()
    assert not (package_root / "data").exists()
    shutdown_container()


def test_wheel_like_app_serves_package_web_and_reports_integration_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    import yeuxq.api.app as app_module

    package_root = tmp_path / "site-packages" / "yeuxq"
    web_root = package_root / "web"
    (web_root / "js").mkdir(parents=True)
    (web_root / "index.html").write_text("<h1>wheel yeuxQ</h1>", encoding="utf-8")
    (web_root / "js" / "app.js").write_text("export const ready = true;", encoding="utf-8")
    monkeypatch.setattr(app_module, "PACKAGE_ROOT", package_root)
    monkeypatch.setattr(app_module, "PROJECT_ROOT", None)
    settings = Settings(data_dir=tmp_path / "runtime")

    application = app_module.create_app(settings, RuntimeSecrets())
    client = TestClient(application)
    headers = {"host": "localhost"}

    root = client.get("/", headers=headers)
    static = client.get("/static/js/app.js", headers=headers)
    integration = client.get("/integration/", headers=headers)
    assert root.status_code == 200
    assert "wheel yeuxQ" in root.text
    assert static.status_code == 200
    assert "ready" in static.text
    assert integration.status_code == 503
    assert integration.json() == {
        "available": False,
        "detail": "integration status is available only from a source checkout",
    }
    assert not (package_root / "data").exists()
