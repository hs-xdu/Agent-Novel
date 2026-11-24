import json
import httpx
import pytest
from llm.client import OpenAIWriter
from llm.errors import IncompleteGeneration
from app.model_settings import ModelSettings
from app.guidance import explain_error
from test_llm import writer_for,response
from test_workflow import prepare
from agent.service import NovelService
from llm.client import DemoWriter
from storage.repository import Repository


@pytest.mark.parametrize('mode',['responses','chat'])
@pytest.mark.parametrize('effort',['auto','none','low'])
async def test_reasoning_sent_only_to_body_tasks(mode,effort):
    requests=[]
    def handler(request):
        data=json.loads(request.content);requests.append(data)
        if mode=='responses':return httpx.Response(200,json=response('正文'))
        return httpx.Response(200,json={'id':'chat_x','object':'chat.completion','created':1,'model':'test','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'正文'}}]})
    w=writer_for(handler);w.api_mode=mode;w.chapter_reasoning=effort
    try:
        await w.text('chapter','{}');await w.text('main','{}')
        key='reasoning' if mode=='responses' else 'reasoning_effort'
        assert key not in requests[1]
        if effort=='auto':assert key not in requests[0]
        else:assert requests[0][key]==({'effort':effort} if mode=='responses' else effort)
    finally:await w.client.close()


async def test_limit_captures_usage_and_only_final_text(caplog):
    data=response('这是尚未完成的正文','incomplete')
    data['incomplete_details']={'reason':'max_output_tokens'}
    data['usage']={'input_tokens':8000,'output_tokens':6000,'total_tokens':14000,'output_tokens_details':{'reasoning_tokens':5700},'input_tokens_details':{'cached_tokens':0}}
    w=writer_for(lambda request:httpx.Response(200,json=data))
    try:
        with pytest.raises(IncompleteGeneration) as caught:await w.text('chapter','{}')
        e=caught.value
        assert e.code=='output_limit' and e.partial_text=='这是尚未完成的正文'
        assert '5700' in e.details and '6000' in e.details
        assert 'max_output_tokens' in e.details
        assert e.partial_text not in caplog.text
        assert '增加超时' in explain_error(str(e),e.diagnostic()).explanation
    finally:await w.client.close()


@pytest.mark.parametrize('text',['未写完的正文',''])
async def test_partial_is_separate_and_cannot_be_finalized_unedited(tmp_path,text):
    service=NovelService(Repository(tmp_path/'projects'),DemoWriter());s=await prepare(service)
    pid=s.project.project_id
    s=service.save_chapter(pid,s.version,1,'原名',1,'原草稿不能丢')
    async def incomplete(*args):raise IncompleteGeneration('未完成',partial_text=text,code='output_limit',details='输出 tokens：6000')
    service.writer.text=incomplete
    with pytest.raises(IncompleteGeneration):await service.generate_chapter(pid,s.version,1)
    after=service.repo.load(pid)
    assert after.chapters[1].draft=='原草稿不能丢' and not after.memories
    if not text:assert not after.incomplete_chapters;return
    item=after.incomplete_chapters[1][0]
    assert item.text==text
    root=service.repo.project_path(pid)/'revisions'/after.version
    assert (root/f'incomplete/chapter_001/{item.candidate_id}.md').read_text(encoding='utf-8')==text
    after=service.adopt_incomplete(pid,after.version,1,item.candidate_id)
    after=service.save_chapter(pid,after.version,1,'原名',1,text)
    with pytest.raises(ValueError,match='补全'):await service.finalize(pid,after.version,1)
    after=service.save_chapter(pid,after.version,1,'原名',1,text+'，用户已补全结尾。')
    assert not after.chapters[1].draft_incomplete
    assert not after.chapters[1].final and not after.memories


def test_existing_settings_default_to_low_and_allow_auto():
    assert ModelSettings().chapter_reasoning=='low'
    assert ModelSettings(chapter_reasoning='auto').chapter_reasoning=='auto'
    with pytest.raises(ValueError):ModelSettings(chapter_reasoning='anything')
