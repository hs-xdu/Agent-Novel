import json
import os
import re

import tiktoken

from models.domain import State, Settings, Memory
from memory.budget import request_cost, input_budget


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_memory_context(state: State, number: int) -> str:
    """正文、规则、指令及 schema 统一计入预算，不截断定稿正文。"""
    chapter=state.chapters[number]
    settings=Settings.model_validate_json(state.documents['settings'].approved)
    data=dict(number=number,revision=chapter.revision,body=chapter.final,settings=settings.model_dump(),history=[])
    people,clues={},{}
    for n,record in sorted(state.memories.items()):
        if n<number:
            people.update({c.character_id:c.model_dump() for c in record.data.characters})
            clues.update({c.clue_id:c.model_dump() for c in record.data.foreshadowing})
    data.update(character_states=list(people.values()),foreshadowing=list(clues.values()))
    if request_cost('memory',encode(data),Memory)>input_budget():
        raise ValueError('本章正文与必要设定超出记忆提取预算，请提高 NOVEL_CONTEXT_TOKENS；正文已保存且不会截断')
    for n,record in sorted(state.memories.items(),reverse=True):
        if n>=number: continue
        data['history'].append(dict(chapter=n,summary=record.data.summary))
        if request_cost('memory',encode(data),Memory)>input_budget(): data['history'].pop(); break
    return encode(data)


def search(state: State, query: str, before: int | None = None) -> list[dict]:
    terms = re.findall(r'[\w]+', query.lower())
    # 中文长句同时按双字片段检索，避免只能整句命中。
    terms += [query[i:i + 2] for i in range(len(query) - 1) if all('\u4e00' <= c <= '\u9fff' for c in query[i:i + 2])]
    hits = []
    for n, chapter in state.chapters.items():
        if not chapter.final or (before is not None and n >= before):
            continue
        for paragraph in chapter.final.split('\n\n'):
            score = sum(term in paragraph.lower() for term in set(terms))
            if score:
                hits.append(dict(chapter=n, revision=chapter.revision, text=paragraph[:1500], score=score))
    return sorted(hits, key=lambda x: (-x['score'], -x['chapter']))[:6]


def build_context(state: State, number: int, extra: str = '', target: int | None = None) -> str:
    settings_doc = state.documents.get('settings')
    if not settings_doc or not settings_doc.approved:
        raise ValueError('请先确认小说设定')
    settings = Settings.model_validate_json(settings_doc.approved)
    chapter = state.chapters.get(number)
    if chapter is None:
        raise ValueError('请先保存章节信息')
    required_keys = ['main', f'volume:{chapter.volume}', f'outline:{number}']
    if any(not state.documents.get(k) or not state.documents[k].approved for k in required_keys):
        raise ValueError('请先确认全书、当前分卷及当前章节大纲')
    data = dict(project=state.project.model_dump(), settings=settings.model_dump(), number=number,
                outlines={k: state.documents[k].approved for k in required_keys},
                extra=extra, target_words=target or state.project.target_chapter_words)
    data['memory'] = []
    data['history'] = []
    tokenizer = tiktoken.get_encoding('cl100k_base')
    budget = int(os.getenv('NOVEL_CONTEXT_TOKENS', '24000')) - int(os.getenv('NOVEL_OUTPUT_TOKENS', '6000')) - 1500
    def fits():
        # 两倍估计提供跨模型编码余量；不是厂商精确 token 计数。
        return 2 * len(tokenizer.encode(encode(data), disallowed_special=())) <= budget
    if not fits():
        raise ValueError('必要设定或大纲超出上下文预算，请精简或提高预算')
    records = [r for n, r in sorted(state.memories.items(), reverse=True) if n < number]
    # 最新人物和伏笔状态始终优先加入，再补近章摘要和检索片段。
    characters, clues = {}, {}
    for record in reversed(records):
        characters.update({c.character_id: c.model_dump() for c in record.data.characters})
        clues.update({c.clue_id: c.model_dump() for c in record.data.foreshadowing})
    data['character_states'] = list(characters.values())
    data['open_clues'] = [c for c in clues.values() if c['status'] == 'open']
    if not fits():
        raise ValueError('人物和伏笔记忆超出预算，请审阅精简记忆或提高预算')
    for record in records:
        item = dict(chapter=record.chapter, revision=record.revision, summary=record.data.summary,
                    events=record.data.events, timeline=record.data.timeline, world_facts=record.data.world_facts)
        data['memory'].append(item)
        if not fits():
            data['memory'].pop()
            break
    previous = state.chapters.get(number - 1)
    history = ([dict(chapter=number - 1, text=previous.final[-1600:])] if previous and previous.final else [])
    history += search(state, data['outlines'][f'outline:{number}'] + extra, before=number)
    for hit in history:
        data['history'].append(hit)
        if not fits():
            data['history'].pop()
    return encode(data)
