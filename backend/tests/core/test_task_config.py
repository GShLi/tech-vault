import pytest

from backend.app.core.config import Settings


def test_task_execution_defaults_to_celery(monkeypatch):
    monkeypatch.delenv("TECHVAULT_TASK_EXECUTION_MODE", raising=False)
    monkeypatch.setenv("TECHVAULT_ENVIRONMENT", "development")

    settings = Settings.from_env()

    assert settings.task_execution_mode == "celery"


def test_task_execution_mode_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("TECHVAULT_ENVIRONMENT", "development")
    monkeypatch.setenv("TECHVAULT_TASK_EXECUTION_MODE", "inline")

    settings = Settings.from_env()

    assert settings.task_execution_mode == "inline"


@pytest.mark.parametrize(
    ("environment", "mode"),
    [("production", "inline"), ("development", "unknown")],
)
def test_task_execution_mode_fails_closed(environment, mode):
    with pytest.raises(ValueError):
        Settings(environment=environment, task_execution_mode=mode)
