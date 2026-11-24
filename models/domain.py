from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Project(Model):
    project_id: str = Field(default_factory=lambda: uuid4().hex)
    title: str = Field(min_length=1, max_length=200)
    genre: str = ''
    description: str = ''
    target_readers: str = ''
    narrative_perspective: str = '第三人称'
    writing_style: str = ''
    target_total_words: int = Field(default=100000, ge=1)
    target_chapter_words: int = Field(default=2000, ge=1, le=20000)
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)

    @field_validator('title', mode='before')
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class Character(Model):
    character_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    personality: str
    abilities: str
    relationships: list[str]


class Faction(Model):
    faction_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str


class Settings(Model):
    worldbuilding: str = Field(min_length=1)
    rules: list[str]
    main_conflict: str
    characters: list[Character]
    factions: list[Faction]

    @model_validator(mode='after')
    def references(self):
        ids = [c.character_id for c in self.characters]
        if len(set(ids)) != len(ids) or any(not x for x in ids):
            raise ValueError('人物 ID 必须非空且唯一')
        if any(r not in ids for c in self.characters for r in c.relationships):
            raise ValueError('人物关系引用了不存在的人物 ID')
        fids = [f.faction_id for f in self.factions]
        if len(set(fids)) != len(fids):
            raise ValueError('势力 ID 必须唯一')
        return self


class Document(Model):
    draft: str = ''
    approved: str = ''


class Chapter(Model):
    number: int = Field(ge=1)
    volume: int = Field(default=1, ge=1)
    title: str = ''
    draft: str = ''
    final: str = ''
    revision: int = 0
    draft_incomplete: bool = False
    status: Literal['draft', 'final'] = 'draft'


class PersonState(Model):
    character_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    state: str
    relationships: list[str]


class Foreshadow(Model):
    clue_id: str = Field(min_length=1)
    description: str
    status: Literal['open', 'resolved']


class Memory(Model):
    summary: str = Field(min_length=1)
    world_facts: list[str]
    characters: list[PersonState]
    events: list[str]
    timeline: list[str]
    foreshadowing: list[Foreshadow]
    conflicts: list[str]


class MemoryRecord(Model):
    chapter: int
    revision: int
    data: Memory


class OutlinePreferences(Model):
    target_words: int = Field(default=1000, ge=200, le=6000)
    detail: Literal['简明', '标准', '详细'] = '简明'

    @classmethod
    def for_kind(cls, kind):
        return cls(target_words={'main':1000,'volume':800,'outline':400}.get(kind,1000),
                   detail={'main':'简明','volume':'标准','outline':'详细'}.get(kind,'简明'))


class PlannedChapter(Model):
    number: int = Field(ge=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class ChapterPlan(Model):
    chapters: list[PlannedChapter] = Field(min_length=1, max_length=30)


class IncompleteDraft(Model):
    candidate_id: str = Field(default_factory=lambda: uuid4().hex)
    text: str
    diagnostic: dict[str,str]
    created_at: str = Field(default_factory=now)


class State(Model):
    schema_version: Literal[1] = 1
    version: str = ''
    project: Project
    documents: dict[str, Document] = Field(default_factory=dict)
    volume_plan_candidates: dict[int, ChapterPlan] = Field(default_factory=dict)
    chapter_goals: dict[int, str] = Field(default_factory=dict)
    outline_preferences: dict[str, OutlinePreferences] = Field(default_factory=dict)
    chapters: dict[int, Chapter] = Field(default_factory=dict)
    incomplete_chapters: dict[int,list[IncompleteDraft]] = Field(default_factory=dict)
    memories: dict[int, MemoryRecord] = Field(default_factory=dict)
    memory_candidates: dict[int, Memory] = Field(default_factory=dict)
    memory_status: Literal['synced', 'pending', 'updating', 'failed'] = 'synced'
    memory_error: str = ''
    memory_diagnostic: dict[str, str] = Field(default_factory=dict)
    pending_from: int | None = None
    operation_id: str = ''
    review_from: int | None = None
