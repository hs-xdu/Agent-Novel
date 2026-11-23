import socket

import pytest

from app.config import DEFAULT_PORT, ensure_available, preview_port


def test_default_preview_port_does_not_target_rop_server(monkeypatch):
    monkeypatch.delenv('NOVEL_PORT', raising=False)
    assert preview_port() == DEFAULT_PORT == 18765


def test_custom_port(monkeypatch):
    monkeypatch.setenv('NOVEL_PORT', '18766')
    assert preview_port() == 18766


@pytest.mark.parametrize('value', ['abc', '0', '65536'])
def test_invalid_port(monkeypatch, value):
    monkeypatch.setenv('NOVEL_PORT', value)
    with pytest.raises(ValueError, match='NOVEL_PORT'):
        preview_port()


def test_occupied_port_explains_project_confusion():
    with socket.socket() as other:
        other.bind(('127.0.0.1', 0))
        other.listen()
        with pytest.raises(ValueError, match='其他项目'):
            ensure_available(other.getsockname()[1])
