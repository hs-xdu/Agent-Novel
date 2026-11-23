import json

import httpx
import pytest
from openai import AsyncOpenAI

from llm.client import OpenAIWriter, ModelError
from models.domain import Memory


def response(text, status='completed'):
    return {'id': 'resp_test', 'object': 'response', 'created_at': 1, 'status': status,
            'model': 'test-model', 'output': [{'id': 'msg_test', 'type': 'message', 'role': 'assistant',
                                              'status': 'completed', 'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}]}


def writer_for(handler):
    writer = OpenAIWriter()
    writer.key, writer.model = 'test-key-not-real', 'test-model'
    writer.client = AsyncOpenAI(api_key=writer.key, max_retries=0,
                               http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return writer


async def test_sdk_responses_text_and_structured_schema():
    requests = []
    payload = dict(summary='测试摘要', world_facts=[], characters=[], events=['事件'], timeline=[], foreshadowing=[], conflicts=[])
    def handler(request):
        data = json.loads(request.content)
        requests.append(data)
        return httpx.Response(200, json=response(json.dumps(payload) if data.get('text') else '正文'))
    writer = writer_for(handler)
    try:
        assert await writer.text('chapter', '{}') == '正文'
        memory = await writer.structured('memory', '{}', Memory)
        assert memory.summary == '测试摘要'
        assert requests[1]['text']['format']['type'] == 'json_schema'
        assert requests[0]['store'] is False
    finally:
        await writer.client.close()


async def test_sdk_auth_error_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={'error': {'message': 'invalid test key', 'type': 'authentication_error'}})
    writer = writer_for(handler)
    try:
        with pytest.raises(ModelError, match='401'):
            await writer.text('chapter', '{}')
        assert len(calls) == 1
    finally:
        await writer.client.close()


async def test_sdk_retry_and_incomplete_response(monkeypatch):
    calls = []
    async def no_sleep(_):
        pass
    monkeypatch.setattr('llm.client.asyncio.sleep', no_sleep)
    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(429, json={'error': {'message': 'limited', 'type': 'rate_limit_error'}})
        return httpx.Response(200, json=response('正文'))
    writer = writer_for(handler)
    try:
        assert await writer.text('chapter', '{}') == '正文'
        assert len(calls) == 3
    finally:
        await writer.client.close()
    writer = writer_for(lambda request: httpx.Response(200, json=response('', status='incomplete')))
    try:
        with pytest.raises(ModelError, match='未完成'):
            await writer.text('chapter', '{}')
    finally:
        await writer.client.close()
