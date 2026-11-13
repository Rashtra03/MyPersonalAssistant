import pytest

from desktop_app import JugnuApp


@pytest.fixture
def app(tmp_path, monkeypatch):
    settings_file = tmp_path / "jugnu_settings.json"
    monkeypatch.setattr("desktop_app.SETTINGS_FILE", str(settings_file))

    # Create the application without launching Tkinter.
    return JugnuApp.__new__(JugnuApp)


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "null",
        '"hello"',
        "123",
    ],
)
def test_load_settings_returns_default_for_non_dict_json(app, tmp_path, content):
    settings_file = tmp_path / "jugnu_settings.json"
    settings_file.write_text(content, encoding="utf-8")

    assert app.load_settings() is True


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"dark_mode": true}', True),
        ('{"dark_mode": false}', False),
        ('{}', True),
    ],
)
def test_load_settings_handles_valid_dict(app, tmp_path, content, expected):
    settings_file = tmp_path / "jugnu_settings.json"
    settings_file.write_text(content, encoding="utf-8")

    assert app.load_settings() is expected


def test_load_settings_handles_invalid_json(app, tmp_path):
    settings_file = tmp_path / "jugnu_settings.json"
    settings_file.write_text("{invalid json", encoding="utf-8")

    assert app.load_settings() is True


def test_load_settings_handles_missing_file(app):
    assert app.load_settings() is True
