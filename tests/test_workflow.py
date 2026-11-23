import asyncio
import json
import os

import pytest
from pydantic import ValidationError

from agent.service import NovelService
from llm.client import DemoWriter, ModelError, OpenAIWriter
from memory.context import build_context
from models.domain import Project, Document
from storage.repository import Repository, ConflictError


@pytest.fixture
def service(tmp_path):
    return NovelService(Repository(tmp_path / 'projects'), DemoWriter())


async def prepare(service, count=1):
    state = service.repo.create(Project(title='旧城来信', description='追寻记忆'))
    pid = state.project.project_id
    state = await service.generate_document(pid, state.version, 'settings', '旧城的故事')
    state = service.save_document(pid, state.version, 'settings', state.documents['settings'].draft, approve=True)
    for key in ['main', 'volume:1']:
        state = await service.generate_document(pid, state.version, key)
        state = service.save_document(pid, state.version, key, state.documents[key].draft, approve=True)
    for n in range(1, count + 1):
        state = service.save_chapter(pid, state.version, n, f'旧城 {n}', 1, '')
        state = await service.generate_document(pid, state.version, f'outline:{n}')
        state = service.save_document(pid, state.version, f'outline:{n}', state.documents[f'outline:{n}'].draft, approve=True)
    return state


async def publish(service, state, n):
    state = await service.generate_chapter(state.project.project_id, state.version, n)
    return await service.finalize(state.project.project_id, state.version, n)


async def test_five_chapter_continuity_restart_export(service):
    state = await prepare(service, 5)
    pid = state.project.project_id
    for n in range(1, 6):
        state = await publish(service, state, n)
        assert state.memory_status == 'synced'
        assert state.memories[n].revision == state.chapters[n].revision
        if n < 5:
            context = json.loads(build_context(state, n + 1))
            assert context['character_states'][0]['character_id'] == 'linzhou'
            assert context['memory'][0]['chapter'] == n
            assert context['open_clues'][0]['clue_id'] == 'copper_key'
            assert context['settings']['rules']
    reloaded = Repository(service.repo.root).load(pid)
    assert len(reloaded.memories) == 5
    assert reloaded.memories[5].data.foreshadowing[0].status == 'resolved'
    assert service.history(pid, '铜钥匙')
    exported = service.repo.export(pid)
    assert exported.index('第1章') < exported.index('第5章')
    snapshot = service.repo.project_path(pid) / 'revisions' / reloaded.version
    assert (snapshot / 'chapters/chapter_005.md').read_text(encoding='utf-8') == reloaded.chapters[5].final
    assert (snapshot / 'settings/characters.json').exists()


async def test_draft_and_regeneration_never_pollute_final(service):
    state = await prepare(service)
    state = await publish(service, state, 1)
    final, memories = state.chapters[1].final, state.memories.copy()
    state = service.save_chapter(state.project.project_id, state.version, 1, '新草稿', 1, '完全不同的草稿')
    assert state.chapters[1].final == final
    assert state.memories == memories
    state = await service.generate_chapter(state.project.project_id, state.version, 1)
    assert state.chapters[1].final == final
    assert state.memories == memories


async def test_settings_candidates_and_outline_confirmation(service):
    state = await prepare(service)
    approved = state.documents['settings'].approved
    state = await service.generate_document(state.project.project_id, state.version, 'settings', '不同想法')
    assert state.documents['settings'].approved == approved
    state = service.save_document(state.project.project_id, state.version, 'main', '候选大纲')
    assert state.documents['main'].approved != '候选大纲'
    assert state.documents['main'].draft == '候选大纲'


async def test_memory_failure_preserves_body_and_retry_is_idempotent(service):
    state = await prepare(service, 2)
    pid = state.project.project_id
    async def fail(*args):
        raise ModelError('模拟限流')
    service.writer.structured = fail
    state = await publish(service, state, 1)
    assert state.memory_status == 'failed' and state.chapters[1].final
    assert not state.memories
    with pytest.raises(ValueError, match='记忆同步'):
        await service.generate_chapter(pid, state.version, 2)
    service = NovelService(Repository(service.repo.root), DemoWriter())
    state = await service.retry_memory(pid)
    assert state.memory_status == 'synced'
    version = state.version
    state = await service.finalize(pid, version, 1)
    assert state.version == version
    assert len(state.memories[1].data.events) == 1


async def test_conflict_candidate_requires_user_resolution(service):
    state = await prepare(service)
    original = service.writer.structured
    async def conflict(task, context, schema):
        result = await original(task, context, schema)
        result.conflicts = ['正文违反铜器规则']
        return result
    service.writer.structured = conflict
    state = await publish(service, state, 1)
    pid = state.project.project_id
    assert state.memory_status == 'failed'
    assert not state.memories and state.memory_candidates[1].conflicts
    data = state.memory_candidates[1].model_copy(deep=True)
    data.conflicts = []
    state = service.edit_memory(pid, state.version, 1, data.model_dump_json(), candidate=True)
    state = await service.retry_memory(pid)
    assert state.memory_status == 'synced' and state.memories[1].data.conflicts == []


async def test_history_revision_rebuild_and_old_snapshot_preserved(service):
    state = await prepare(service, 3)
    for n in range(1, 4):
        state = await publish(service, state, n)
    pid, old_version = state.project.project_id, state.version
    final3 = state.chapters[3].final
    state = service.save_chapter(pid, state.version, 1, '修订', 1, '林舟在旧城取得另一封来信。')
    state = await service.finalize(pid, state.version, 1)
    assert state.memory_status == 'synced'
    assert state.memories[1].revision == 2 and state.review_from == 2
    assert state.chapters[3].final == final3
    old = service.repo.project_path(pid) / 'revisions' / old_version / 'state.json'
    assert json.loads(old.read_text(encoding='utf-8'))['chapters']['1']['revision'] == 1


async def test_memory_manual_edit_rebuilds_following(service):
    state = await prepare(service, 2)
    for n in (1, 2):
        state = await publish(service, state, n)
    data = state.memories[1].data.model_copy(deep=True)
    data.summary = '用户修订的摘要'
    state = service.edit_memory(state.project.project_id, state.version, 1, data.model_dump_json())
    assert state.pending_from == 2 and state.memory_status == 'pending'
    state = await service.retry_memory(state.project.project_id)
    assert state.memories[1].data.summary == '用户修订的摘要'
    assert state.memory_status == 'synced'


def test_project_isolation_validation_and_stale_version(service):
    a = service.repo.create(Project(title='甲'))
    b = service.repo.create(Project(title='乙'))
    service.update_project(a.project.project_id, a.version, {'title': '甲改', 'project_id': b.project.project_id})
    assert service.repo.load(b.project.project_id).project.title == '乙'
    with pytest.raises(ConflictError):
        service.update_project(a.project.project_id, a.version, {'title': '旧状态'})
    with pytest.raises(ValidationError):
        Project(title='', target_chapter_words=0)
    with pytest.raises(ValueError):
        service.repo.load('../escape')


def test_atomic_pointer_failure_and_orphan_snapshot(service, monkeypatch):
    state = service.repo.create(Project(title='安全存储'))
    pid, version = state.project.project_id, state.version
    state.project.title = '不能发布'
    def fail(*args):
        raise OSError('simulated crash before pointer replace')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        service.repo.save(state, version)
    assert service.repo.load(pid).version == version
    assert service.repo.load(pid).project.title == '安全存储'


def test_partial_snapshot_failure_preserves_current(service, monkeypatch):
    state = service.repo.create(Project(title='完整快照'))
    def fail(path, state):
        service.repo._write(path / 'project.json', '{}')
        raise OSError('interrupted snapshot')
    monkeypatch.setattr(service.repo, '_write_snapshot', fail)
    with pytest.raises(OSError):
        service.repo.save(state, state.version)
    assert service.repo.load(state.project.project_id).version == state.version


def test_single_instance_lock(tmp_path):
    a, b = Repository(tmp_path), Repository(tmp_path)
    a.acquire_instance()
    try:
        with pytest.raises(ValueError, match='占用'):
            b.acquire_instance()
    finally:
        a.close()
    b.acquire_instance()
    b.close()


async def test_generation_failure_does_not_replace_draft(service):
    state = await prepare(service)
    state = service.save_chapter(state.project.project_id, state.version, 1, '标题', 1, '用户正文')
    async def fail(*args):
        raise ModelError('失败')
    service.writer.text = fail
    with pytest.raises(ModelError):
        await service.generate_chapter(state.project.project_id, state.version, 1)
    assert service.repo.load(state.project.project_id).chapters[1].draft == '用户正文'


async def test_concurrent_generation_and_save_rejected(service):
    state = await prepare(service)
    started, release = asyncio.Event(), asyncio.Event()
    async def wait(*args):
        started.set()
        await release.wait()
        return '延迟结果'
    service.writer.text = wait
    task = asyncio.create_task(service.generate_chapter(state.project.project_id, state.version, 1))
    await started.wait()
    try:
        with pytest.raises(ValueError, match='任务正在进行'):
            await service.generate_chapter(state.project.project_id, state.version, 1)
        with pytest.raises(ValueError, match='任务正在进行'):
            service.save_chapter(state.project.project_id, state.version, 1, '', 1, '编辑')
    finally:
        release.set()
        await task


async def test_external_state_change_rejects_generation_result(service):
    state = await prepare(service)
    async def change(*args):
        other = service.repo.load(state.project.project_id)
        other.project.title = '外部修改'
        service.repo.save(other, other.version)
        return '过期生成'
    service.writer.text = change
    with pytest.raises(ConflictError):
        await service.generate_chapter(state.project.project_id, state.version, 1)
    assert service.repo.load(state.project.project_id).chapters[1].draft == ''


async def test_rewrite_selection_and_stale_text(service):
    state = await prepare(service)
    body = '开头😀\n\n选中段落\n\n结尾'
    start, end = body.index('选中'), body.index('\n\n结尾')
    suggestion = await service.rewrite(state.project.project_id, state.version, 1, body, start, end, '增加动作')
    edited = service.apply_rewrite(body, body, start, end, suggestion)
    assert edited.startswith('开头😀\n\n') and edited.endswith('\n\n结尾')
    with pytest.raises(ConflictError):
        service.apply_rewrite(body + '变更', body, start, end, suggestion)
    assert service.repo.load(state.project.project_id).chapters[1].draft == ''


async def test_context_budget_and_chapter_order(service, monkeypatch):
    state = await prepare(service, 2)
    with pytest.raises(ValueError, match='顺序定稿'):
        await service.generate_chapter(state.project.project_id, state.version, 2)
    monkeypatch.setenv('NOVEL_CONTEXT_TOKENS', '100')
    with pytest.raises(ValueError, match='预算'):
        build_context(state, 1)


async def test_settings_and_relationship_validation(service):
    state = await prepare(service)
    settings = json.loads(state.documents['settings'].approved)
    settings['characters'][0]['relationships'] = ['missing']
    with pytest.raises(ValidationError):
        service.save_document(state.project.project_id, state.version, 'settings', json.dumps(settings))
    with pytest.raises(ValueError):
        service.save_document(state.project.project_id, state.version, '../../bad', '内容')


async def test_openai_missing_config(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    writer = OpenAIWriter()
    with pytest.raises(ModelError, match='配置'):
        await writer.text('chapter', '{}')


@pytest.mark.parametrize('failure_point', [1, 2, 3, 4, 5])
async def test_restart_at_each_finalize_checkpoint(service, monkeypatch, failure_point):
    state = await prepare(service)
    state = await service.generate_chapter(state.project.project_id, state.version, 1)
    pid = state.project.project_id
    original = service.repo._write_snapshot
    count = 0
    def interrupt(path, data):
        nonlocal count
        count += 1
        original(path, data)
        if count == failure_point:
            raise SystemExit('simulated process interruption')
    monkeypatch.setattr(service.repo, '_write_snapshot', interrupt)
    with pytest.raises(SystemExit):
        await service.finalize(pid, state.version, 1)
    restarted = NovelService(Repository(service.repo.root), DemoWriter())
    recovered = restarted.repo.load(pid)
    assert recovered.chapters[1].draft == state.chapters[1].draft
    if failure_point == 1:
        assert not recovered.chapters[1].final
        recovered = await restarted.finalize(pid, recovered.version, 1)
    else:
        assert recovered.chapters[1].final
        recovered = await restarted.retry_memory(pid)
    assert recovered.memory_status == 'synced'
    assert recovered.memories[1].revision == recovered.chapters[1].revision == 1
    assert len(recovered.memories[1].data.events) == 1


def test_invalid_snapshot_path_cannot_escape(service):
    state = service.repo.create(Project(title='路径检查'))
    version = state.version
    state.documents['../../escape'] = Document(draft='非法路径')
    with pytest.raises(ValueError, match='路径'):
        service.repo.save(state, version)
    assert service.repo.load(state.project.project_id).version == version
