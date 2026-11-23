import asyncio
import logging
import os

from dotenv import load_dotenv
from nicegui import app, ui

from agent.service import NovelService
from llm.client import create_writer
from models.domain import Project
from storage.repository import Repository
from app.config import APP_ID, APP_NAME, ensure_available, preview_port

LABELS = {'genre': '题材', 'description': '创作想法 / 简介', 'target_readers': '目标读者',
          'narrative_perspective': '叙事视角', 'writing_style': '语言风格',
          'target_total_words': '目标总字数', 'target_chapter_words': '单章目标字数'}


def build_app(service: NovelService):
    @app.get('/api/health')
    def health():
        return {'app': APP_ID, 'name': APP_NAME, 'version': '0.1.0'}

    @ui.page('/')
    def index():
        session = {'pid': None, 'number': 1, 'volume': 1, 'tab': '项目管理', 'kind': 'settings', 'doc_index': 1}
        with ui.header().classes('items-center justify-between bg-slate-900'):
            ui.label(APP_NAME).classes('text-xl font-bold')
            ui.label('离线演示 · 内容为固定示例' if os.getenv('NOVEL_MODE') == 'demo' else '本地项目 · AI 辅助创作').classes('text-sm')
        ui.add_css('body {background:#f5f6f8} .q-textarea textarea {line-height:1.8} .q-tab {font-size:15px}')

        async def confirm(message):
            with ui.dialog() as dialog, ui.card().classes('w-96'):
                ui.label(message).classes('text-base')
                with ui.row():
                    ui.button('确认', on_click=lambda: dialog.submit(True))
                    ui.button('取消', on_click=lambda: dialog.submit(False)).props('flat')
            return await dialog

        async def perform(action, message='已保存'):
            before = service.repo.load(session['pid']).version if session['pid'] else None
            with ui.dialog().props('persistent') as progress, ui.card():
                ui.spinner()
                ui.label('正在处理，请稍候…')
            progress.open()
            try:
                result = action()
                if asyncio.iscoroutine(result):
                    await result
                ui.notify(message, type='positive')
                workspace.refresh()
            except Exception as exc:
                logging.getLogger(__name__).warning('UI operation failed: %s', type(exc).__name__)
                ui.notify(str(exc), type='negative', timeout=10000)
                if session['pid'] and service.repo.load(session['pid']).version != before:
                    workspace.refresh()
            finally:
                progress.close()

        def select_project(e):
            session['pid'] = e.value
            session['number'] = 1
            workspace.refresh()

        @ui.refreshable
        def project_picker():
            projects = service.repo.list_projects()
            with ui.row().classes('w-full items-end'):
                ui.select({p.project_id: p.title for p in projects}, value=session['pid'],
                          label='当前小说项目', on_change=select_project).classes('w-80').props('outlined')
                title = ui.input('新小说名称', placeholder='必填，例如：旧城来信', validation={
                    '请先填写小说名称': lambda value: bool((value or '').strip()),
                    '小说名称不能超过 200 字': lambda value: len((value or '').strip()) <= 200,
                }).classes('w-64').props('maxlength=200')
                async def create():
                    if not title.validate():
                        ui.notify('请先填写新小说名称，再创建项目', type='warning')
                        title.run_method('focus')
                        return
                    def action():
                        project = Project(title=title.value.strip())
                        service.repo.create(project)
                        session['pid'] = project.project_id
                        project_picker.refresh()
                    await perform(action, '项目已创建')
                ui.button('创建项目', icon='add', on_click=create)
                ui.button('重新加载', icon='refresh', on_click=lambda: workspace.refresh()).props('flat')

        @ui.refreshable
        def workspace():
            pid = session['pid']
            if not pid:
                with ui.card().classes('w-full p-8'):
                    ui.label('从一个故事想法开始').classes('text-2xl')
                    ui.label('创建项目 → 确认设定与大纲 → 创作章节 → 审阅定稿 → 更新记忆').classes('text-slate-600')
                return
            state = service.repo.load(pid)
            expected = state.version
            ui.label(expected).props('data-testid=revision').classes('hidden')
            with ui.tabs().classes('w-full bg-white rounded') as tabs:
                project_tab = ui.tab('项目管理', icon='folder')
                settings_tab = ui.tab('设定与大纲', icon='account_tree')
                chapter_tab = ui.tab('章节创作', icon='edit_note')
                memory_tab = ui.tab('小说记忆', icon='psychology')
            tabs.on_value_change(lambda e: session.update(tab=e.value))
            ui.label(f'{state.project.title} · 已定稿 {sum(bool(c.final) for c in state.chapters.values())} 章 · 记忆：' +
                     {'synced': '已同步', 'pending': '待更新', 'updating': '更新中 / 可重试恢复', 'failed': '更新失败'}[state.memory_status]).classes('text-slate-600')
            if state.review_from:
                ui.label(f'历史内容已变动，请复核第 {state.review_from} 章及后续正文。').classes('text-amber-800')
            with ui.tab_panels(tabs, value=session['tab']).classes('w-full bg-transparent'):
                with ui.tab_panel(project_tab), ui.card().classes('w-full'):
                    fields = {'title': ui.input('小说名称', value=state.project.title).classes('w-full')}
                    with ui.grid(columns=2).classes('w-full'):
                        for key, label in LABELS.items():
                            value = getattr(state.project, key)
                            fields[key] = (ui.number(label, value=value, min=1, format='%.0f') if isinstance(value, int)
                                           else ui.textarea(label, value=value).props('autogrow'))
                    async def save_project():
                        values = {k: (int(v.value) if k.startswith('target_') and k.endswith('words') else v.value) for k, v in fields.items()}
                        await perform(lambda: service.update_project(pid, expected, values))
                        project_picker.refresh()
                    ui.button('保存项目信息', on_click=save_project)
                    ui.button('导出正式章节 Markdown', icon='download', on_click=lambda: ui.download.content(
                        service.repo.export(pid), 'novel.md', media_type='text/markdown'))

                with ui.tab_panel(settings_tab):
                    ui.label('AI 生成只保存候选。审阅后点击“确认生效”，才会用于后续创作。').classes('text-slate-600')
                    with ui.row().classes('items-end'):
                        kind = ui.select({'settings': '基础设定', 'main': '全书大纲', 'volume': '分卷大纲', 'outline': '章节大纲'}, value=session['kind'], label='文档类型').classes('w-48')
                        index_field = ui.number('卷号 / 章节号', value=session['doc_index'], min=1, format='%.0f')
                    doc_area = ui.column().classes('w-full')
                    def render_doc():
                        session.update(kind=kind.value, doc_index=int(index_field.value or 1))
                        key = kind.value if kind.value in ('settings', 'main') else f'{kind.value}:{int(index_field.value or 1)}'
                        doc = state.documents.get(key)
                        doc_area.clear()
                        with doc_area:
                            ui.label(f'当前文档：{key}').classes('font-bold')
                            if key == 'settings':
                                ui.label('设定使用 JSON 编辑：worldbuilding、rules、main_conflict、characters、factions；可先让 AI 生成。人物关系填人物 ID。').classes('text-sm text-slate-600')
                            request = ui.textarea('本次生成要求', value=state.project.description).classes('w-full').props('autogrow')
                            editor = ui.textarea('候选 / 编辑内容', value=(doc.draft or doc.approved) if doc else '').classes('w-full').props('outlined input-style="min-height:320px"')
                            with ui.row():
                                ui.button('AI 生成 / 重新生成', on_click=lambda: perform(
                                    lambda: service.generate_document(pid, expected, key, request.value), '候选已生成，请审阅')).props('outline')
                                ui.button('保存候选', on_click=lambda: perform(lambda: service.save_document(pid, expected, key, editor.value)))
                                async def approve():
                                    if await confirm('确认将当前内容设为正式版本？已有正式版本将保留在历史修订中。'):
                                        await perform(lambda: service.save_document(pid, expected, key, editor.value, approve=True), '已确认生效')
                                ui.button('确认生效', on_click=approve)
                            with ui.expansion('查看正式版本').classes('w-full'):
                                ui.code(doc.approved if doc else '尚未确认', language='json' if key == 'settings' else 'markdown').classes('w-full')
                    kind.on_value_change(lambda _: render_doc())
                    index_field.on_value_change(lambda _: render_doc())
                    render_doc()

                with ui.tab_panel(chapter_tab):
                    with ui.row().classes('items-end'):
                        number = ui.number('章节编号', value=session['number'], min=1, format='%.0f')
                        def load_chapter():
                            session['number'] = int(number.value or 1)
                            workspace.refresh()
                        ui.button('加载章节', on_click=load_chapter).props('outline')
                        ui.label('已有章节：' + ('、'.join(str(n) for n in sorted(state.chapters)) or '暂无'))
                    n = session['number']
                    chapter = state.chapters.get(n)
                    ui.label(f'当前编辑：第 {n} 章').classes('text-xl')
                    with ui.row().classes('w-full'):
                        chapter_title = ui.input('章节名称', value=chapter.title if chapter else '').classes('grow')
                        volume = ui.number('所属分卷', value=chapter.volume if chapter else 1, min=1, format='%.0f')
                        target = ui.number('本章目标字数', value=state.project.target_chapter_words, min=1, max=20000, format='%.0f')
                    outline = state.documents.get(f'outline:{n}')
                    with ui.expansion('本章正式大纲', value=True).classes('w-full'):
                        ui.markdown(outline.approved if outline and outline.approved else '请先保存章节信息，再到“设定与大纲”生成并确认本章大纲。')
                    extra = ui.textarea('额外创作要求').classes('w-full').props('autogrow')
                    body = ui.textarea('章节正文', value=(chapter.draft or chapter.final) if chapter else '').classes('w-full').props('outlined input-style="min-height:420px"')
                    count = ui.label()
                    count.bind_text_from(body, 'value', backward=lambda v: f'正文字符数（去除空白）：{len("".join((v or "").split()))}')
                    def save_body():
                        return service.save_chapter(pid, expected, n, chapter_title.value, int(volume.value), body.value)
                    with ui.row():
                        ui.button('保存章节草稿 / 信息', on_click=lambda: perform(save_body))
                        async def generate():
                            async def action():
                                saved = save_body()
                                await service.generate_chapter(pid, saved.version, n, extra.value, int(target.value))
                            await perform(action, '正文草稿已生成，请审阅')
                        ui.button('AI 创作 / 整章重写', on_click=generate).props('outline')
                        async def finalize():
                            if await confirm('确认将当前正文定稿，并自动更新记忆？'):
                                async def action():
                                    saved = save_body()
                                    result = await service.finalize(pid, saved.version, n)
                                    if result.memory_status != 'synced':
                                        ui.notify('正文已保存，记忆未同步：' + result.memory_error, type='warning', timeout=15000)
                                await perform(action, '正式正文已保存')
                        ui.button('确认定稿并更新记忆', icon='check', on_click=finalize)
                    ui.separator()
                    instruction = ui.input('段落修改要求', placeholder='例如：增加动作细节，保持人物克制').classes('w-full')
                    async def rewrite():
                        async def action():
                            selection = await ui.run_javascript(f'''const root = getHtmlElement({body.id});
                                const el = root.matches('textarea') ? root : root.querySelector('textarea');
                                return {{body: el.value, prefix: el.value.slice(0, el.selectionStart), selected: el.value.slice(el.selectionStart, el.selectionEnd)}};''')
                            original = selection['body']
                            start = len(selection['prefix'])
                            end = start + len(selection['selected'])
                            suggestion = await service.rewrite(pid, expected, n, original, start, end, instruction.value)
                            with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl'):
                                ui.label('审阅段落修改建议').classes('text-lg')
                                proposal = ui.textarea('替换内容', value=suggestion).classes('w-full').props('autogrow')
                                async def apply():
                                    try:
                                        current = await ui.run_javascript(f"const root = getHtmlElement({body.id}); return (root.matches('textarea') ? root : root.querySelector('textarea')).value")
                                        if service.repo.load(pid).version != expected:
                                            raise ValueError('项目已更新，请重新加载后重试')
                                        body.value = service.apply_rewrite(current, original, start, end, proposal.value)
                                        dialog.close()
                                        ui.notify('已应用，请保存章节草稿')
                                    except Exception as exc:
                                        ui.notify(str(exc), type='negative')
                                ui.button('应用修改建议', on_click=apply)
                                ui.button('取消修改', on_click=dialog.close).props('flat')
                            dialog.open()
                        # 保留编辑器与选区，不刷新工作区。
                        try:
                            await action()
                        except Exception as exc:
                            ui.notify(str(exc), type='negative', timeout=10000)
                    ui.button('修改选中段落', on_click=rewrite).props('outline')
                    with ui.expansion('预览当前正文').classes('w-full'):
                        ui.markdown().bind_content_from(body, 'value')
                    with ui.expansion('查看当前正式正文').classes('w-full'):
                        ui.markdown(chapter.final if chapter and chapter.final else '尚未定稿')

                with ui.tab_panel(memory_tab):
                    if state.memory_error:
                        ui.label(state.memory_error).classes('text-red-700')
                    ui.button('重试 / 恢复记忆同步', icon='sync', on_click=lambda: perform(lambda: service.retry_memory(pid), '记忆同步任务已处理，请查看状态'))
                    ui.label('按章节记录来源与修订；人物与伏笔 ID 在后续章节沿用。修改正式记忆后，后续记忆需要重新同步。').classes('text-slate-600')
                    for no, record in sorted(state.memories.items()):
                        with ui.expansion(f'第 {no} 章 · 正文修订 {record.revision} · {record.data.summary[:60]}').classes('w-full bg-white'):
                            ui.markdown(record.data.summary)
                            editor = ui.textarea('记忆 JSON', value=record.data.model_dump_json(indent=2)).classes('w-full').props('autogrow')
                            ui.button('保存记忆修订', on_click=lambda no=no, editor=editor: perform(
                                lambda: service.edit_memory(pid, expected, no, editor.value)))
                    for no, data in sorted(state.memory_candidates.items()):
                        with ui.expansion(f'第 {no} 章 · 待处理记忆候选', value=True).classes('w-full bg-amber-50'):
                            ui.label('请结合正文和设定处理冲突，清空已解决的 conflicts，确认后点击重试同步。')
                            candidate = ui.textarea('候选记忆 JSON', value=data.model_dump_json(indent=2)).classes('w-full').props('autogrow')
                            ui.button('确认候选记忆修订', on_click=lambda no=no, candidate=candidate: perform(
                                lambda: service.edit_memory(pid, expected, no, candidate.value, candidate=True)))
                    ui.separator()
                    query = ui.input('搜索历史正文', placeholder='人物、事件或关键词').classes('w-full')
                    results = ui.column().classes('w-full')
                    def find():
                        results.clear()
                        with results:
                            hits = service.history(pid, query.value or '')
                            if not hits:
                                ui.label('没有匹配的正式章节片段')
                            for hit in hits:
                                ui.label(f'第 {hit["chapter"]} 章 · 修订 {hit["revision"]}').classes('font-bold')
                                ui.label(hit['text']).classes('whitespace-pre-wrap')
                    ui.button('检索', on_click=find).props('outline')
                    with ui.expansion('历史章节全文').classes('w-full'):
                        for no, c in sorted(state.chapters.items()):
                            if c.final:
                                with ui.expansion(f'第 {no} 章 {c.title}'):
                                    ui.markdown(c.final)

        with ui.column().classes('w-full max-w-6xl mx-auto p-4 gap-4'):
            project_picker()
            workspace()


def main():
    load_dotenv()
    port = preview_port()
    ensure_available(port)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    # SDK 的 HTTP 请求日志可能包含地址；应用不记录密钥、正文和提示词。
    logging.getLogger('httpx').setLevel(logging.WARNING)
    repository = Repository(os.getenv('NOVEL_DATA_DIR', 'projects'))
    repository.acquire_instance()
    app.on_shutdown(repository.close)
    build_app(NovelService(repository, create_writer()))
    ui.run(host='127.0.0.1', port=port, title=APP_NAME, reload=False, show=False)


if __name__ == '__main__':
    main()
