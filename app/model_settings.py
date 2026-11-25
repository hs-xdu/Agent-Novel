import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal

import keyring
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, field_validator


class ModelSettings(BaseModel):
    mode: str = 'openai'
    api_mode: str = 'responses'
    base_url: str = 'https://api.openai.com/v1'
    model: str = ''
    key: SecretStr = SecretStr('')
    timeout: int = Field(default=120, ge=5, le=600)
    chapter_reasoning: Literal['auto','none','low','medium','high','xhigh'] = 'low'
    memory_reasoning: Literal['auto','none','low','medium','high','xhigh'] = 'none'

    @field_validator('base_url')
    @classmethod
    def address(cls, value):
        value = value.strip().rstrip('/')
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('请填写不含密钥、用户名、查询参数的 HTTP API 基础地址')
        return value

    @field_validator('mode', 'api_mode')
    @classmethod
    def choices(cls, value, info):
        if value not in ({'openai', 'demo'} if info.field_name == 'mode' else {'responses', 'chat'}):
            raise ValueError('不支持的接口模式')
        return value


class SettingsStore:
    def __init__(self, root: Path, credentials=keyring):
        self.root, self.credentials = root, credentials
        self.path = root / '.desktop' / 'model.json'

    def load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            data['key'] = self.credentials.get_password('Shiguang', str(self.root.resolve())) or ''
            return ModelSettings.model_validate(data)
        env = dotenv_values(self.root / '.env')
        return ModelSettings(mode=env.get('NOVEL_MODE') or 'openai', model=env.get('OPENAI_MODEL') or '',
                             base_url=env.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1',
                             key=env.get('OPENAI_API_KEY') or '', timeout=int(env.get('NOVEL_TIMEOUT') or 120))

    def save(self, settings):
        if settings.mode != 'demo' and (not settings.model.strip() or not settings.key.get_secret_value().strip()):
            raise ValueError('请填写模型名称和 API 密钥')
        # 密钥存入系统凭据库，不写入普通 JSON 或日志。
        self.credentials.set_password('Shiguang', str(self.root.resolve()), settings.key.get_secret_value())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(settings.model_dump_json(exclude={'key'}, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)
