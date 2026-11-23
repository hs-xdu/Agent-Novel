import pytest

from app.init_env import initialize_env


@pytest.mark.parametrize('existing', [None, b''])
def test_missing_or_empty_env_is_initialized(tmp_path, existing):
    template = b'OPENAI_API_KEY=\nOPENAI_MODEL=\n'
    (tmp_path / '.env.example').write_bytes(template)
    if existing is not None:
        (tmp_path / '.env').write_bytes(existing)
    assert initialize_env(tmp_path)
    assert (tmp_path / '.env').read_bytes() == template


def test_existing_configuration_is_never_overwritten(tmp_path):
    (tmp_path / '.env').write_bytes(b'OPENAI_MODEL=my-config\n')
    (tmp_path / '.env.example').write_bytes(b'OPENAI_MODEL=\n')
    assert not initialize_env(tmp_path)
    assert (tmp_path / '.env').read_bytes() == b'OPENAI_MODEL=my-config\n'


def test_empty_template_does_not_create_env(tmp_path):
    (tmp_path / '.env.example').write_bytes(b'')
    with pytest.raises(ValueError):
        initialize_env(tmp_path)
    assert not (tmp_path / '.env').exists()
