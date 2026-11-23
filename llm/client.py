import asyncio
import json
import logging
import os
import time
from typing import Protocol, TypeVar

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ValidationError
import tiktoken

from models.domain import Settings, Memory
from prompts import SYSTEM, TASKS

T = TypeVar('T', bound=BaseModel)
log = logging.getLogger(__name__)


class ModelError(ValueError):
    pass


class Writer(Protocol):
    async def text(self, task: str, context: str) -> str: ...
    async def structured(self, task: str, context: str, schema: type[T]) -> T: ...


class OpenAIWriter:
    def __init__(self, settings=None):
        self.key = settings.key.get_secret_value() if settings else os.getenv('OPENAI_API_KEY', '')
        self.model = settings.model if settings else os.getenv('OPENAI_MODEL', '')
        self.base_url = settings.base_url if settings else os.getenv('OPENAI_BASE_URL') or None
        self.timeout = settings.timeout if settings else float(os.getenv('NOVEL_TIMEOUT', '120'))
        self.api_mode = settings.api_mode if settings else 'responses'
        self.client = None

    def _client(self):
        if not self.key or not self.model:
            raise ModelError('请在“大模型 API 设置”中配置密钥和模型；网页版也可在 .env 中配置，或选择 demo 演示')
        if self.client is None:
            self.client = AsyncOpenAI(api_key=self.key, base_url=self.base_url,
                                      timeout=self.timeout, max_retries=0)
        return self.client

    async def _request(self, task, context, schema=None):
        client = self._client()
        output_limit = int(os.getenv('NOVEL_OUTPUT_TOKENS', '6000'))
        budget = int(os.getenv('NOVEL_CONTEXT_TOKENS', '24000')) - output_limit
        token_count = len(tiktoken.get_encoding('cl100k_base').encode(SYSTEM + TASKS[task] + context, disallowed_special=()))
        if budget < 1 or token_count * 2 > budget:
            raise ModelError('请求超出上下文预算，请精简输入或提高上下文预算')
        for attempt in range(3):
            started = time.monotonic()
            try:
                if self.api_mode == 'chat':
                    instruction = SYSTEM + '\n' + TASKS[task]
                    if schema:
                        instruction += '\n只输出 JSON，必须符合此 schema：' + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                    arguments = dict(model=self.model, messages=[{'role': 'system', 'content': instruction}, {'role': 'user', 'content': context}])
                    if schema:
                        arguments['response_format'] = {'type': 'json_object'}
                    else:
                        arguments['max_tokens'] = output_limit
                    result = await client.chat.completions.create(**arguments)
                    if not result.choices or result.choices[0].finish_reason != 'stop':
                        raise ModelError('模型输出未完成，请调整输出预算或选择支持的模型')
                    value = result.choices[0].message.content
                    if not value:
                        raise ModelError('模型未返回有效内容')
                    return schema.model_validate_json(value) if schema else value
                kwargs = dict(model=self.model, instructions=SYSTEM + '\n' + TASKS[task], input=context,
                              max_output_tokens=output_limit, store=False)
                if schema:
                    result = await client.responses.parse(**kwargs, text_format=schema)
                else:
                    result = await client.responses.create(**kwargs)
                log.info('model task=%s elapsed=%.2f request=%s', task, time.monotonic() - started, getattr(result, '_request_id', ''))
                if result.status != 'completed':
                    raise ModelError('模型输出未完成，请增加输出预算或缩短输入后重试')
                value = result.output_parsed if schema else result.output_text
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise ModelError('模型未返回有效内容，可能拒绝了请求')
                return value
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                retryable = not isinstance(exc, APIStatusError) or exc.status_code in (408, 409, 429) or exc.status_code >= 500
                if attempt == 2 or not retryable:
                    code = getattr(exc, 'status_code', 'network')
                    raise ModelError(f'模型请求失败（{code}），请检查配置、网络或额度后重试') from exc
                await asyncio.sleep(2 ** attempt)
            except ValidationError as exc:
                if attempt == 2:
                    raise ModelError('结构化输出校验失败，正式数据未被覆盖') from exc
        raise ModelError('模型调用失败')

    async def text(self, task, context):
        return await self._request(task, context)

    async def structured(self, task, context, schema):
        return await self._request(task, context, schema)


class DemoWriter:
    """仅用于无密钥的功能演示与验收；不模拟真实模型质量。"""
    async def text(self, task, context):
        await asyncio.sleep(0)
        data = json.loads(context)
        number = data.get('number', 1)
        if task == 'rewrite':
            return '风穿过旧城的窄巷，林舟握紧铜钥匙，终于迈出了那一步。'
        if task == 'chapter':
            return f'第{number}章 旧城来信\n\n林舟沿着旧城的石阶向前。铜钥匙在掌心微微发热，他记得同伴的嘱托，没有贸然推门。\n\n门后传来三下敲击。他停住脚步，确认暗号后才低声回应。这一次，他要查清信件的来源。\n\n一张新地图从门缝递出，角落的徽记与钥匙上的刻痕完全一致。'
        return f'# {TASKS[task].split("，")[0]}\n\n目标：追查旧城来信。\n\n人物：林舟。\n\n冲突：信任与隐瞒。\n\n事件：发现铜钥匙与地图关联。\n\n结尾：门后传来熟悉的暗号。'

    async def structured(self, task, context, schema):
        await asyncio.sleep(0)
        if schema is Settings:
            return Settings(worldbuilding='旧城中，记忆可被封存在铜器里。', rules=['铜器只能保存持有者亲历的记忆。'],
                            main_conflict='林舟追查失踪家人的来信。',
                            characters=[dict(character_id='linzhou', name='林舟', personality='谨慎而执着', abilities='辨认铜器中的记忆', relationships=[])],
                            factions=[dict(faction_id='archive', name='旧城档案馆', description='保存城市的历史')])
        data = json.loads(context)
        number = data.get('number', 1)
        settings = data.get('settings', {})
        people = settings.get('characters', [])
        return Memory(summary=f'第{number}章，主角发现铜钥匙与地图的关联。', world_facts=[],
                      characters=[dict(character_id=p['character_id'], name=p['name'], state=f'完成第{number}章的调查', relationships=p['relationships']) for p in people],
                      events=[f'第{number}章发现地图线索'], timeline=[f'调查第{number}日：取得新线索'],
                      foreshadowing=[dict(clue_id='copper_key', description='铜钥匙的来历', status='resolved' if number >= 5 else 'open')], conflicts=[])


def create_writer() -> Writer:
    mode = os.getenv('NOVEL_MODE', 'openai')
    if mode not in ('demo', 'openai'):
        raise ValueError('NOVEL_MODE 仅支持 openai 或 demo')
    return DemoWriter() if mode == 'demo' else OpenAIWriter()
