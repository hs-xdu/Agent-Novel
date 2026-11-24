import json
import os
import re
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from models.domain import Project, State, now


class ConflictError(ValueError):
    pass


class Repository:
    """CURRENT 是唯一提交点；未发布快照在重启后不会成为正式数据。"""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.instance_lock = FileLock(str(self.root / '.instance.lock'))

    def acquire_instance(self):
        try:
            self.instance_lock.acquire(timeout=0)
        except Timeout as exc:
            raise ValueError('数据目录已被另一个应用实例占用') from exc

    def close(self):
        if self.instance_lock.is_locked:
            self.instance_lock.release()

    def project_path(self, project_id: str) -> Path:
        if not re.fullmatch(r'[a-f0-9]{32}', project_id):
            raise ValueError('无效项目 ID')
        path = self.root / project_id
        if path.resolve().parent != self.root or path.is_symlink():
            raise ValueError('项目路径越界')
        return path

    def load(self, project_id: str) -> State:
        path = self.project_path(project_id)
        version = (path / 'CURRENT').read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'[a-f0-9]{32}', version):
            raise ValueError('项目版本指针损坏')
        state = State.model_validate_json((path / 'revisions' / version / 'state.json').read_text(encoding='utf-8'))
        if state.project.project_id != project_id or state.version != version:
            raise ValueError('快照标识不一致')
        return state

    def list_projects(self) -> list[Project]:
        return [self.load(p.name).project for p in sorted(self.root.iterdir())
                if p.is_dir() and re.fullmatch(r'[a-f0-9]{32}', p.name) and (p / 'CURRENT').exists()]

    def create(self, project: Project) -> State:
        state = State(project=project)
        return self.save(state, expected='')

    def save(self, state: State, expected: str) -> State:
        state = State.model_validate(state.model_dump())
        path = self.project_path(state.project.project_id)
        path.mkdir(exist_ok=True)
        with FileLock(str(path / '.write.lock')):
            current = (path / 'CURRENT').read_text(encoding='utf-8').strip() if (path / 'CURRENT').exists() else ''
            if current != expected:
                raise ConflictError('数据已更新，请重新加载后再操作')
            state.version = uuid4().hex
            state.project.updated_at = now()
            revision = path / 'revisions' / state.version
            revision.mkdir(parents=True)
            self._write_snapshot(revision, state)
            pointer = path / f'.CURRENT.{uuid4().hex}.tmp'
            try:
                self._write(pointer, state.version)
                os.replace(pointer, path / 'CURRENT')
            finally:
                pointer.unlink(missing_ok=True)
            return state

    @staticmethod
    def _write(path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

    def _write_snapshot(self, root: Path, state: State):
        def write(name, value):
            self._write(root / name, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
        write('state.json', state.model_dump_json(indent=2))
        write('project.json', state.project.model_dump())
        for key, doc in state.documents.items():
            if not re.fullmatch(r'settings|main|(?:volume|outline):[1-9]\d*', key):
                raise ValueError('快照包含无效文档路径')
            safe = key.replace(':', '_')
            write(f'drafts/{safe}.md', doc.draft)
            write(f'{"settings" if key == "settings" else "outline"}/{safe}.md', doc.approved)
        if state.documents.get('settings') and state.documents['settings'].approved:
            settings = json.loads(state.documents['settings'].approved)
            write('settings/worldbuilding.md', settings['worldbuilding'])
            write('settings/characters.json', settings['characters'])
            write('settings/factions.json', settings['factions'])
        for number, chapter in state.chapters.items():
            write(f'drafts/chapter_{number:03d}.md', chapter.draft)
            if chapter.final:
                write(f'chapters/chapter_{number:03d}.md', chapter.final)
        for number,items in state.incomplete_chapters.items():
            for item in items:write(f'incomplete/chapter_{number:03d}/{item.candidate_id}.md',item.text)
        write('outline/chapters.json', {str(n): c.model_dump(exclude={'draft', 'final'}) for n, c in state.chapters.items()})
        write('memory/records.json', {str(n): m.model_dump() for n, m in state.memories.items()})
        write('memory/story_summary.md', '\n\n'.join(f'第{n}章：{m.data.summary}' for n, m in sorted(state.memories.items())))
        for name, field in [('timeline', 'timeline'), ('character_states', 'characters'), ('foreshadowing', 'foreshadowing')]:
            write(f'memory/{name}.json', [{'chapter': n, 'revision': m.revision, 'items': m.data.model_dump()[field]} for n, m in sorted(state.memories.items())])
        write('operations/current.json', {'operation_id': state.operation_id, 'status': state.memory_status, 'pending_from': state.pending_from, 'error': state.memory_error})

    def export(self, project_id: str) -> str:
        state = self.load(project_id)
        return f'# {state.project.title}\n\n' + '\n\n'.join(
            f'## 第{n}章 {c.title}\n\n{c.final}' for n, c in sorted(state.chapters.items()) if c.final)
