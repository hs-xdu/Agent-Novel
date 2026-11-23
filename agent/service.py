import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from llm.client import Writer
from memory.context import build_context, encode, search
from models.domain import Chapter, Document, Memory, MemoryRecord, Project, Settings, State
from storage.repository import Repository, ConflictError

log = logging.getLogger(__name__)


class NovelService:
    def __init__(self, repository: Repository, writer: Writer):
        self.repo, self.writer = repository, writer
        self.locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def operation(self, pid):
        lock = self.locks.setdefault(pid, asyncio.Lock())
        if lock.locked():
            raise ValueError('该项目有任务正在进行，请等待完成')
        async with lock:
            yield

    def _editable(self, pid, expected):
        if self.locks.get(pid) and self.locks[pid].locked():
            raise ValueError('该项目有任务正在进行，请稍后保存')
        state = self.repo.load(pid)
        if state.version != expected:
            raise ConflictError('项目已更新，请重新加载')
        return state

    def update_project(self, pid, expected, values):
        state = self._editable(pid, expected)
        immutable = {'project_id', 'created_at', 'updated_at'}
        state.project = Project.model_validate({**state.project.model_dump(), **{k: v for k, v in values.items() if k not in immutable}})
        return self.repo.save(state, expected)

    @staticmethod
    def _key(key):
        if not re.fullmatch(r'settings|main|(?:volume|outline):[1-9]\d*', key):
            raise ValueError('文档编号无效')

    def save_document(self, pid, expected, key, text, approve=False):
        self._key(key)
        if not text.strip():
            raise ValueError('内容不能为空')
        if key == 'settings':
            text = Settings.model_validate_json(text).model_dump_json(indent=2)
        state = self._editable(pid, expected)
        doc = state.documents.setdefault(key, Document())
        changed = approve and text != doc.approved
        doc.draft = text
        if approve:
            doc.approved = text
        if changed and key == 'settings' and any(c.final for c in state.chapters.values()):
            state.pending_from = min(n for n, c in state.chapters.items() if c.final)
            state.memory_status = 'pending'
            state.memory_candidates.clear()
            state.review_from = state.pending_from
        return self.repo.save(state, expected)

    async def generate_document(self, pid, expected, key, idea=''):
        self._key(key)
        async with self.operation(pid):
            state = self.repo.load(pid)
            if state.version != expected:
                raise ConflictError('项目已更新，请重新加载')
            task = key.split(':')[0]
            task = 'outline' if task == 'outline' else task
            parents = [] if task == 'settings' else ['settings']
            if task in ('volume', 'outline'):
                parents.append('main')
            if task == 'outline':
                chapter = state.chapters.get(int(key.split(':')[1]))
                if not chapter:
                    raise ValueError('请先保存章节信息')
                parents.append(f'volume:{chapter.volume}')
            if any(not state.documents.get(k) or not state.documents[k].approved for k in parents):
                raise ValueError('请先确认上级设定和大纲')
            context = encode(dict(project=state.project.model_dump(), key=key, request=idea,
                                  parents={k: state.documents[k].approved for k in parents},
                                  existing=state.documents.get(key, Document()).approved))
            result = (await self.writer.structured(task, context, Settings)).model_dump_json(indent=2) if task == 'settings' else await self.writer.text(task, context)
            state.documents.setdefault(key, Document()).draft = result
            return self.repo.save(state, expected)

    def save_chapter(self, pid, expected, number, title, volume, body):
        state = self._editable(pid, expected)
        chapter = state.chapters.setdefault(number, Chapter(number=number))
        chapter.title, chapter.volume, chapter.draft = title, volume, body
        Chapter.model_validate(chapter.model_dump())
        return self.repo.save(state, expected)

    async def generate_chapter(self, pid, expected, number, extra='', target=None):
        async with self.operation(pid):
            state = self.repo.load(pid)
            if state.version != expected:
                raise ConflictError('项目已更新，请重新加载')
            if state.memory_status != 'synced':
                raise ValueError('请先完成记忆同步，再生成章节')
            if any(n not in state.chapters or not state.chapters[n].final for n in range(1, number)):
                raise ValueError('请先按顺序定稿前面的章节')
            context = build_context(state, number, extra, target)
            result = await self.writer.text('chapter', context)
            state.chapters[number].draft = result
            return self.repo.save(state, expected)

    async def rewrite(self, pid, expected, number, body, start, end, instruction):
        async with self.operation(pid):
            state = self.repo.load(pid)
            if state.version != expected:
                raise ConflictError('项目已更新，请重新加载')
            if not 0 <= start < end <= len(body):
                raise ValueError('请在正文编辑器中选择需要修改的段落')
            context = json.loads(build_context(state, number, instruction))
            context.update(selected=body[start:end], before=body[max(0, start - 1000):start], after=body[end:end + 1000])
            replacement = await self.writer.text('rewrite', encode(context))
            return replacement

    @staticmethod
    def apply_rewrite(current, original, start, end, replacement):
        if current != original:
            raise ConflictError('正文已变化，请重新选择段落生成修改建议')
        return current[:start] + replacement + current[end:]

    async def finalize(self, pid, expected, number):
        async with self.operation(pid):
            state = self.repo.load(pid)
            if state.version != expected:
                raise ConflictError('项目已更新，请重新加载')
            chapter = state.chapters[number]
            if not chapter.draft.strip():
                raise ValueError('请先保存非空章节草稿')
            build_context(state, number)
            if any(n not in state.chapters or not state.chapters[n].final for n in range(1, number)):
                raise ValueError('请先按顺序定稿前面的章节')
            if chapter.final != chapter.draft:
                had_final = bool(chapter.final)
                chapter.final = chapter.draft
                chapter.revision += 1
                chapter.status = 'final'
                state.pending_from = min(state.pending_from or number, number)
                state.memory_status = 'pending'
                state.operation_id = uuid4().hex
                state.memory_candidates = {n: m for n, m in state.memory_candidates.items() if n < number}
                if had_final and any(n > number and c.final for n, c in state.chapters.items()):
                    state.review_from = number + 1
                state = self.repo.save(state, expected)
            if state.memory_status != 'synced':
                await self._sync(state)
            return self.repo.load(pid)

    async def retry_memory(self, pid):
        async with self.operation(pid):
            return await self._sync(self.repo.load(pid))

    def _validate_memory(self, state, number, data):
        settings = Settings.model_validate_json(state.documents['settings'].approved)
        ids = {c.character_id for c in settings.characters}
        for n, record in state.memories.items():
            if n < number:
                ids.update(c.character_id for c in record.data.characters)
        ids.update(c.character_id for c in data.characters)
        if any(r not in ids for c in data.characters for r in c.relationships):
            raise ValueError('记忆中存在无效人物关系引用')
        person_ids = [c.character_id for c in data.characters]
        clue_ids = [c.clue_id for c in data.foreshadowing]
        if len(set(person_ids)) != len(person_ids) or len(set(clue_ids)) != len(clue_ids):
            raise ValueError('记忆中的人物或伏笔 ID 重复')
        names = {c.character_id: c.name for c in settings.characters}
        if any(c.character_id in names and names[c.character_id] != c.name for c in data.characters):
            raise ValueError('记忆人物 ID 与正式设定姓名不一致')

    async def _sync(self, state):
        pid = state.project.project_id
        if state.memory_status == 'synced':
            return state
        start = state.pending_from or 1
        state.memory_status = 'updating'
        state.memory_error = ''
        state = self.repo.save(state, state.version)
        try:
            for n, chapter in sorted(state.chapters.items()):
                if n < start or not chapter.final:
                    continue
                candidate = state.memory_candidates.get(n)
                if candidate is None:
                    context = json.loads(build_context(state, n))
                    context.update(body=chapter.final, revision=chapter.revision)
                    candidate = await self.writer.structured('memory', encode(context), Memory)
                    state.memory_candidates[n] = candidate
                    state = self.repo.save(state, state.version)
                self._validate_memory(state, n, candidate)
                if candidate.conflicts:
                    raise ValueError('发现设定冲突：' + '；'.join(candidate.conflicts) + '。请在小说记忆中审阅候选')
                state.memories[n] = MemoryRecord(chapter=n, revision=chapter.revision, data=candidate)
                state.memory_candidates.pop(n, None)
                state.pending_from = n + 1
                state = self.repo.save(state, state.version)
            state.memory_status, state.pending_from, state.memory_error = 'synced', None, ''
            state = self.repo.save(state, state.version)
        except Exception as exc:
            # 再读取已发布版本，避免存储故障时覆盖更新。
            state = self.repo.load(pid)
            state.memory_status = 'failed'
            state.memory_error = str(exc)[:1000]
            state = self.repo.save(state, state.version)
            log.warning('memory project=%s operation=%s failed=%s', pid, state.operation_id, type(exc).__name__)
        return state

    def edit_memory(self, pid, expected, number, text, candidate=False):
        state = self._editable(pid, expected)
        data = Memory.model_validate_json(text)
        if number not in state.chapters or not state.chapters[number].final:
            raise ValueError('记忆必须关联已定稿章节')
        self._validate_memory(state, number, data)
        if data.conflicts:
            raise ValueError('请先处理 conflicts 中的冲突，再确认保存')
        if candidate:
            state.memory_candidates[number] = data
        else:
            if number not in state.memories:
                raise ValueError('该章没有正式记忆，请审阅候选后重试同步')
            state.memories[number].data = data
            if any(n > number for n in state.memories):
                state.pending_from = min(state.pending_from or number + 1, number + 1)
                state.memory_status = 'pending'
                state.memory_candidates = {n: m for n, m in state.memory_candidates.items() if n <= number}
        return self.repo.save(state, expected)

    def history(self, pid, query):
        return search(self.repo.load(pid), query)
