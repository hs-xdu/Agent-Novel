import json
import httpx
import pytest
from app.model_settings import ModelSettings,SettingsStore
from app.guidance import explain_error
from test_llm import writer_for,response
from models.domain import Memory


@pytest.mark.parametrize('mode',['responses','chat'])
@pytest.mark.parametrize('memory_effort',['auto','none','low'])
async def test_memory_setting_is_independent_and_reaches_structured_request(mode,memory_effort):
    requests=[]
    memory=dict(summary='记忆摘要',world_facts=[],characters=[],events=[],timeline=[],foreshadowing=[],conflicts=[])
    def handler(request):
        data=json.loads(request.content);requests.append(data)
        if mode=='responses':
            structured=bool(data.get('text'))
            return httpx.Response(200,json=response(json.dumps(memory) if structured else '正文'))
        return httpx.Response(200,json={'id':'chat_test','object':'chat.completion','created':1,'model':'test','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(memory) if data.get('response_format') else '正文'}}]})
    w=writer_for(handler);w.api_mode=mode;w.chapter_reasoning='medium';w.memory_reasoning=memory_effort
    try:
        assert (await w.structured('memory','{}',Memory)).summary=='记忆摘要'
        await w.text('chapter','{}');await w.text('main','{}')
        key='reasoning' if mode=='responses' else 'reasoning_effort'
        assert requests[1][key]==({'effort':'medium'} if mode=='responses' else 'medium')
        assert key not in requests[2]
        if memory_effort=='auto':assert key not in requests[0]
        else:assert requests[0][key]==({'effort':memory_effort} if mode=='responses' else memory_effort)
        if mode=='responses':assert requests[0]['max_output_tokens']==6000
    finally:await w.client.close()


def test_old_desktop_config_defaults_memory_to_none_without_rewriting_key(tmp_path):
    from test_desktop import Credentials
    credentials=Credentials();store=SettingsStore(tmp_path,credentials)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(dict(mode='openai',api_mode='responses',base_url='https://api.openai.com/v1',model='test',chapter_reasoning='low',timeout=180)),encoding='utf-8')
    credentials.set_password('Shiguang',str(tmp_path.resolve()),'test-secret')
    setting=store.load()
    assert setting.memory_reasoning=='none' and setting.chapter_reasoning=='low'
    assert setting.timeout==180 and setting.key.get_secret_value()=='test-secret'
    assert ModelSettings().memory_reasoning=='none'


def test_memory_limit_guidance_points_to_memory_setting():
    issue=explain_error('输出已用完',dict(code='output_limit',details='任务：memory'),True)
    assert '记忆整理思考强度' in issue.next_step
    assert '正文思考强度' not in issue.next_step
    assert '无需重写' in issue.next_step
