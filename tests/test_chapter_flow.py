import json
import pytest
from agent.service import NovelService
from llm.client import DemoWriter
from memory.context import build_memory_context,encode
from memory.budget import request_cost,input_budget
from models.domain import Memory,ChapterPlan
from storage.repository import Repository
from test_workflow import prepare,publish


@pytest.fixture
def service(tmp_path):return NovelService(Repository(tmp_path/'projects'),DemoWriter())


async def test_next_chapter_is_created_or_resumed_without_duplicates(service):
    s=await prepare(service);pid=s.project.project_id
    resumed,n=service.begin_chapter(pid,s.version)
    assert n==1 and resumed.version==s.version
    s=await publish(service,s,1)
    s,n=service.begin_chapter(pid,s.version)
    assert n==2 and s.chapters[2].volume==1
    same,n=service.begin_chapter(pid,s.version)
    assert same.version==s.version and len(same.chapters)==2
    s=await service.generate_document(pid,s.version,'outline:2')
    assert s.documents['outline:2'].draft


async def test_volume_plan_is_candidate_until_explicitly_confirmed(service):
    s=await prepare(service);pid=s.project.project_id
    s=await service.propose_chapters(pid,s.version,1,3)
    assert list(s.chapters)==[1]
    plan=s.volume_plan_candidates[1]
    s=service.accept_chapters(pid,s.version,1,plan.model_dump_json())
    assert list(s.chapters)==[1,2,3,4]
    assert s.chapter_goals[2] and not s.memories
    with pytest.raises(ValueError):service.accept_chapters(pid,s.version,1,plan.model_dump_json())


async def test_memory_request_has_full_body_without_book_outline_bloat(service,monkeypatch):
    s=await prepare(service)
    s.chapters[1].final='林舟取得线索。'*260
    s.chapters[1].revision=1
    s.documents['main'].approved='不应复制到记忆提取中的全书大纲。'*500
    s.documents['volume:1'].approved='分卷大纲。'*500
    context=build_memory_context(s,1);data=json.loads(context)
    assert data['body']==s.chapters[1].final
    assert 'outlines' not in data and 'project' not in data
    assert request_cost('memory',context,Memory)<=input_budget()
    monkeypatch.setenv('NOVEL_CONTEXT_TOKENS','7000')
    with pytest.raises(ValueError,match='正文已保存且不会截断'):build_memory_context(s,1)


async def test_outline_generation_waits_for_failed_memory_recovery(service):
    s=await prepare(service);pid=s.project.project_id
    s.memory_status='failed';s.pending_from=1;s=service.repo.save(s,s.version)
    with pytest.raises(ValueError,match='记忆尚未同步'):
        await service.generate_document(pid,s.version,'outline:2')
    assert not service.repo.load(pid).documents.get('outline:2')


async def test_memory_failure_diagnostic_survives_reload(service):
    from llm.errors import ModelError
    s=await prepare(service)
    async def fail(*args):raise ModelError('等待模型响应超过120秒',code='timeout',details='异常：APITimeoutError',reference='persistent-reference')
    service.writer.structured=fail
    s=await publish(service,s,1)
    restored=service.repo.load(s.project.project_id)
    assert restored.memory_status=='failed' and restored.chapters[1].final
    assert restored.memory_diagnostic['code']=='timeout'
    assert restored.memory_diagnostic['reference']=='persistent-reference'
