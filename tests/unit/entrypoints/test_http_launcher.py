import importlib

import pytest

from app.entrypoints import http_launcher


def _fail_import_with(name: str):
    real_import = importlib.import_module

    def fake(module: str, *args, **kwargs):
        if module == "app.entrypoints.http":
            msg = f"No module named {name!r}"
            raise ModuleNotFoundError(msg, name=name)
        return real_import(module, *args, **kwargs)

    return fake


@pytest.mark.parametrize("missing", ["fastapi", "pymongo", "uvicorn.config"])
def test_a_missing_http_only_package_explains_the_extra(monkeypatch, capsys, missing):
    monkeypatch.setattr(importlib, "import_module", _fail_import_with(missing))

    with pytest.raises(SystemExit) as exc_info:
        http_launcher.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "'http' extra" in err
    assert missing.split(".")[0] in err


def test_any_other_missing_module_is_not_hidden(monkeypatch):
    """Only the known http-only packages get the friendly message; a real
    bug (a typo'd import, a missing core package) must still raise."""
    monkeypatch.setattr(importlib, "import_module", _fail_import_with("app.nope"))

    with pytest.raises(ModuleNotFoundError):
        http_launcher.main()


def test_runs_the_http_entry_point_when_installed(monkeypatch):
    calls = []
    http = importlib.import_module("app.entrypoints.http")
    monkeypatch.setattr(http, "main", lambda: calls.append("main"))

    http_launcher.main()

    assert calls == ["main"]
