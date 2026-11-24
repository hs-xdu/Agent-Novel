import asyncio
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.desktop import Window, ApiDialog
from app.model_settings import SettingsStore, ModelSettings
from storage.repository import Repository


class Credentials:
    def __init__(self): self.values = {}
    def get_password(self, service, name): return self.values.get((service,name))
    def set_password(self, service, name, value): self.values[service,name] = value


@pytest.fixture
def window(qtbot, tmp_path):
    store=SettingsStore(tmp_path,Credentials()); store.save(ModelSettings(mode='demo'))
    widget=Window(Repository(tmp_path/'projects'),store)
    qtbot.addWidget(widget); widget.show()
    return widget


def create(window):
    window.new_title.setText('桌面验收小说'); window.create_project()
    assert window.state.project.title=='桌面验收小说'


def test_settings_secure_persistence_and_legacy_import(tmp_path):
    (tmp_path/'.env').write_text('OPENAI_API_KEY=legacy-test-key\nOPENAI_MODEL=qwen-test\nOPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1\n',encoding='utf-8')
    store=SettingsStore(tmp_path,Credentials())
    assert store.load().key.get_secret_value()=='legacy-test-key'
    store.save(ModelSettings(key='new-test-key',model='new-model',api_mode='chat'))
    assert 'new-test-key' not in store.path.read_text()
    assert store.load().key.get_secret_value()=='new-test-key'
    assert store.load().api_mode=='chat'


@pytest.mark.parametrize('url',['https://host/v1?key=secret','file:///abc','https://user:pass@host/v1'])
def test_settings_reject_secret_addresses(url):
    with pytest.raises(ValueError): ModelSettings(base_url=url)


def test_native_create_validation_and_edit_recovery(window,qtbot):
    assert window.windowTitle()=='拾光 · 小说写作助手'
    assert window.tabs.count()==4
    window.create_project(); assert window.state is None
    create(window)
    window.body.setPlainText('未定稿的文字😀'); window.document.setPlainText('尚未确认的设定')
    window.stash()
    second=Window(window.repo,window.store); qtbot.addWidget(second)
    assert second.body.toPlainText()=='未定稿的文字😀'
    assert second.document.toPlainText()=='尚未确认的设定'
    assert not second.state.memories and not second.state.chapters


def test_desktop_background_full_workflow(window,qtbot):
    create(window)
    def wait(): qtbot.waitUntil(lambda:window.job is None,timeout=30000)
    for kind in ['settings','main','volume']:
        window.kind.setCurrentIndex(window.kind.findData(kind))
        window.generate_document(); wait()
        assert window.document.toPlainText()
        window.confirm=lambda _:True
        window.save_document(True)
    window.save_chapter()
    window.kind.setCurrentIndex(window.kind.findData('outline'))
    window.generate_document(); wait(); window.save_document(True)
    window.generate_chapter(); wait()
    assert '林舟' in window.body.toPlainText()
    window.finalize(); wait()
    assert window.state.chapters[1].final
    assert window.state.memory_status=='synced'
    assert window.state.memories[1].revision==1
    assert '林舟' in window.repo.export(window.state.project.project_id)


def test_long_job_keeps_navigation_responsive_and_prevents_close(window,qtbot):
    create(window)
    async def delayed(service):
        await asyncio.sleep(.3)
        return 'finished'
    finished=[]
    window.submit(delayed,finished.append)
    window.tabs.setCurrentIndex(2)
    assert window.tabs.currentIndex()==2
    assert not window.close()
    qtbot.waitUntil(lambda:window.job is None,timeout=5000)
    assert finished==['finished']


def test_api_dialog_saves_and_applies_without_restart(window,qtbot):
    dialog=ApiDialog(window); qtbot.addWidget(dialog)
    dialog.model.setText('qwen3.8-max'); dialog.key.setText('test-key')
    dialog.base.setText('https://dashscope.aliyuncs.com/compatible-mode/v1')
    dialog.mode.setCurrentText('openai'); dialog.protocol.setCurrentText('chat')
    dialog.reasoning.setCurrentIndex(dialog.reasoning.findData('none'))
    dialog.save()
    assert window.settings.model=='qwen3.8-max'
    assert window.store.load().api_mode=='chat'
    assert window.store.load().chapter_reasoning=='none'
    assert 'test-key' not in window.store.path.read_text()


def test_failed_background_request_preserves_edit_and_reenables_window(window,qtbot,monkeypatch):
    create(window)
    window.body.setPlainText('不能丢失的草稿')
    messages=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:messages.append(args[-1]))
    async def fail(service): raise ValueError('模拟模型超时')
    window.submit(fail)
    qtbot.waitUntil(lambda:window.job is None,timeout=5000)
    assert messages==['模拟模型超时']
    assert window.body.toPlainText()=='不能丢失的草稿'
    assert window.tabs.widget(2).isEnabled()
    assert '不能丢失的草稿' in (window.repo.project_path(window.state.project.project_id)/'desktop-drafts.json').read_text(encoding='utf-8')


def test_outline_options_are_per_document_and_restore(window,qtbot):
    create(window)
    window.kind.setCurrentIndex(window.kind.findData('main'))
    assert window.outline_words.value()==1000
    assert window.outline_detail.currentText()=='简明'
    window.outline_words.setValue(700); window.outline_detail.setCurrentText('标准')
    window.idea.setText('突出主角成长')
    window.kind.setCurrentIndex(window.kind.findData('volume'))
    assert window.outline_words.value()==800
    window.outline_words.setValue(500); window.stash()
    window.kind.setCurrentIndex(window.kind.findData('main'))
    assert window.outline_words.value()==700 and window.idea.text()=='突出主角成长'
    window.stash()
    second=Window(window.repo,window.store); qtbot.addWidget(second)
    second.kind.setCurrentIndex(second.kind.findData('main'))
    assert second.outline_words.value()==700 and second.outline_detail.currentText()=='标准'
    second.kind.setCurrentIndex(second.kind.findData('settings'))
    assert second.outline_options.isHidden()
    second.navigation.setCurrentRow(2)
    assert second.tabs.currentIndex()==2 and second.page_title.text()=='章节创作'


def test_guided_chapter_flow_stays_in_chapter_workspace(window,qtbot):
    create(window);window.confirm=lambda _:True
    def wait():qtbot.waitUntil(lambda:window.job is None,timeout=30000)
    for kind in ['settings','main','volume']:
        window.kind.setCurrentIndex(window.kind.findData(kind));window.generate_document();wait();window.save_document(True)
    window.navigation.setCurrentRow(2);window.begin_next()
    assert window.state.chapters[1].volume==1
    window.generate_chapter_outline();wait()
    assert window.outline.toPlainText()
    window.accept_outline_generate();wait()
    assert window.chapter_steps.currentIndex()==1 and window.body.toPlainText()
    window.finalize();wait()
    assert window.state.memory_status=='synced'
    window.begin_next()
    assert window.chapter_number==2 and 2 in window.state.chapters
    window.generate_chapter_outline();wait()
    assert window.outline.toPlainText() and window.navigation.currentRow()==2


def test_chapter_outline_edit_is_shared_with_management_editor(window,qtbot):
    create(window)
    window.kind.setCurrentIndex(window.kind.findData('outline'))
    window.document.setPlainText('从管理页编辑的大纲')
    assert window.outline.toPlainText()=='从管理页编辑的大纲'
    window.outline.setPlainText('从章节页编辑的大纲')
    assert window.document.toPlainText()=='从章节页编辑的大纲'


def test_failed_memory_result_is_not_reported_as_success(window,qtbot,monkeypatch):
    from models.domain import Chapter,Document,Settings
    create(window)
    state=window.state
    state.chapters[1]=Chapter(number=1,final='正式正文',draft='正式正文',revision=1,status='final')
    state.chapters[2]=Chapter(number=2)
    state.documents['outline:2']=Document(approved='第二章大纲')
    state.documents['settings']=Document(approved=Settings(worldbuilding='世界',rules=[],main_conflict='冲突',characters=[],factions=[]).model_dump_json());state.documents['main']=Document(approved='全书');state.documents['volume:1']=Document(approved='分卷')
    state.memory_status='failed';state.pending_from=1
    state.memory_error='等待模型响应超过120秒'
    state.memory_diagnostic={'code':'timeout','details':'异常：APITimeoutError','reference':'test-ref'}
    window.state=window.repo.save(state,state.version);window.number.setValue(2);window.refresh()
    assert not window.generate_body_button.isEnabled()
    assert not window.chapter_retry.isHidden()
    assert '下一步' in window.chapter_status.text()
    assert '记忆待更新' in window.chapter_list.item(0).text()
    shown=[];monkeypatch.setattr(window,'show_issue',lambda issue,**kwargs:shown.append(issue))
    window.submit(lambda service:window.state,message='记忆已同步，可以继续创作。')
    qtbot.waitUntil(lambda:window.job is None,timeout=5000)
    assert '失败' in window.statusBar().currentMessage()
    assert '记忆已同步' not in window.statusBar().currentMessage()
    assert shown and shown[0].settings and '300' in shown[0].next_step
    settings=[];monkeypatch.setattr('app.desktop.ApiDialog.exec',lambda dialog:settings.append(True))
    window.chapter_settings.click();assert settings==[True]
    state=window.repo.load(window.state.project.project_id);state.memory_status='synced';state.memory_error='';state.pending_from=None
    window.state=window.repo.save(state,state.version);window.refresh()
    assert window.generate_body_button.isEnabled()
    assert window.chapter_retry.isHidden()


def test_failure_dialog_text_is_selectable_and_all_details_copy(window,qtbot,monkeypatch):
    from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QLabel
    from PySide6.QtCore import Qt
    from app.guidance import explain_error
    issue=explain_error('等待模型超时',{'code':'timeout','reference':'copy-reference','details':'本次耗时：120秒'},True)
    def inspect_dialog(dialog):
        labels=[label for label in dialog.findChildren(QLabel) if label.text() in (issue.title,issue.explanation,'下一步：'+issue.next_step)]
        assert len(labels)==3
        assert all(label.textInteractionFlags()&Qt.TextInteractionFlag.TextSelectableByMouse for label in labels)
        copy=next(button for button in dialog.findChildren(QPushButton) if button.text()=='复制全部说明')
        copy.click()
        text=QApplication.clipboard().text()
        assert issue.explanation in text and issue.next_step in text and 'copy-reference' in text and '正文已保存' in text
        dialog.accept();return 0
    monkeypatch.setattr(QDialog,'exec',inspect_dialog)
    window.show_issue(issue,memory=True)


def test_partial_candidate_is_visible_without_overwriting_editor(window,qtbot,monkeypatch):
    from test_workflow import prepare
    from agent.service import NovelService
    from llm.client import DemoWriter
    from llm.errors import IncompleteGeneration
    state=asyncio.run(prepare(NovelService(window.repo,DemoWriter())))
    window.refresh_projects(state.project.project_id)
    window.body.setPlainText('现有草稿保留')
    async def partial(*args):raise IncompleteGeneration('输出未完成',partial_text='模型返回的半章',code='output_limit')
    monkeypatch.setattr('app.desktop.DemoWriter.text',partial)
    monkeypatch.setattr(window,'show_issue',lambda *args,**kwargs:None)
    window.generate_chapter()
    qtbot.waitUntil(lambda:window.job is None,timeout=5000)
    assert window.body.toPlainText()=='现有草稿保留'
    assert window.partial_pick.count()==1 and not window.partial_box.isHidden()
    assert window.partial_content.isHidden()
    window.partial_box.setChecked(True)
    assert not window.partial_content.isHidden()
    assert window.partial_text.toPlainText()=='模型返回的半章'
    assert '另存' in window.statusBar().currentMessage()
    window.confirm=lambda _:True;window.adopt_partial()
    assert window.body.toPlainText()=='模型返回的半章'
    assert window.state.chapters[1].draft_incomplete
