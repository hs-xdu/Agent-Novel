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
    dialog.save()
    assert window.settings.model=='qwen3.8-max'
    assert window.store.load().api_mode=='chat'
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
