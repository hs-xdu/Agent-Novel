"""真实浏览器端到端测试；优先本机 Edge，否则使用 Playwright Chromium。"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope='module')
def browser_app(tmp_path_factory):
    directory = tmp_path_factory.mktemp('ui')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTEST', 'NICEGUI_'))}
    env.update(NOVEL_MODE='demo', NOVEL_PORT=str(port), NOVEL_DATA_DIR=str(directory / 'projects'), PYTHONUTF8='1')
    root = Path(__file__).resolve().parents[1]
    with (directory / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-m', 'app.main'], cwd=root, env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        try:
            url = f'http://127.0.0.1:{port}'
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail((directory / 'server.log').read_text(encoding='utf-8'))
                try:
                    if httpx.get(url, timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                pytest.fail('UI server did not start')
            with sync_playwright() as playwright:
                edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
                options = {'executable_path': str(edge)} if edge.exists() else {}
                browser = playwright.chromium.launch(headless=True, **options)
                page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                page.set_default_timeout(15000)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                try:
                    yield page, url, directory, errors
                finally:
                    page.screenshot(path=str(directory / 'last-page.png'), full_page=True)
                    (directory / 'last-page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)


def wait_saved(page):
    revision = page.locator('[data-testid="revision"]')
    expect(revision).to_have_count(1)
    previous = getattr(page, '_saved_revision', None)
    if previous:
        expect(revision).not_to_have_text(previous, timeout=30000)
    expect(page.get_by_text('正在处理，请稍候…', exact=True)).to_be_hidden(timeout=30000)
    page._saved_revision = revision.inner_text()


def choose_document(page, label):
    page.locator('.q-select').filter(has=page.get_by_text('文档类型', exact=True)).click()
    page.get_by_role('option', name=label, exact=True).click()
    keys = {'基础设定': 'settings', '全书大纲': 'main', '分卷大纲': 'volume:1', '章节大纲': 'outline:1'}
    expect(page.get_by_text('当前文档：' + keys[label], exact=True)).to_be_visible()


def approve(page):
    page.get_by_role('button', name='确认生效', exact=True).click()
    page.get_by_role('button', name='确认', exact=True).click()
    wait_saved(page)


def test_browser_full_creation_edit_finalize_and_memory(browser_app):
    page, url, directory, errors = browser_app
    page.goto(url)
    page.get_by_label('新小说名称', exact=True).fill('浏览器验收小说')
    page.get_by_role('button', name='创建项目', exact=True).click()
    expect(page.get_by_role('tab', name='项目管理')).to_be_visible()
    wait_saved(page)
    page.get_by_label('题材', exact=True).fill('悬疑奇幻')
    page.get_by_role('button', name='保存项目信息', exact=True).click()
    wait_saved(page)
    page.get_by_role('tab', name='设定与大纲').click()
    for label in ['基础设定', '全书大纲', '分卷大纲']:
        choose_document(page, label)
        page.get_by_role('button', name='AI 生成 / 重新生成', exact=True).click()
        wait_saved(page)
        expect(page.get_by_label('候选 / 编辑内容', exact=True)).not_to_have_value('')
        approve(page)
    page.get_by_role('tab', name='章节创作').click()
    page.get_by_label('章节名称', exact=True).fill('旧城初探')
    page.get_by_role('button', name='保存章节草稿 / 信息', exact=True).click()
    wait_saved(page)
    page.get_by_role('tab', name='设定与大纲').click()
    choose_document(page, '章节大纲')
    page.get_by_role('button', name='AI 生成 / 重新生成', exact=True).click()
    wait_saved(page)
    approve(page)
    page.get_by_role('tab', name='章节创作').click()
    page.get_by_role('button', name='AI 创作 / 整章重写', exact=True).click()
    wait_saved(page)
    body = page.get_by_label('章节正文', exact=True)
    original = body.input_value()
    assert '林舟' in original
    body.fill('开头😀\n\n待修改段落\n\n结尾')
    page.get_by_label('段落修改要求', exact=True).fill('增加动作')
    body.evaluate("el => {el.focus(); el.setSelectionRange(el.value.indexOf('待修改'), el.value.indexOf('\\n\\n结尾'));}")
    page.get_by_role('button', name='修改选中段落', exact=True).click()
    expect(page.get_by_text('审阅段落修改建议', exact=True)).to_be_visible()
    page.get_by_role('button', name='应用修改建议', exact=True).click()
    expect(body).to_have_value('开头😀\n\n风穿过旧城的窄巷，林舟握紧铜钥匙，终于迈出了那一步。\n\n结尾')
    page.get_by_role('button', name='确认定稿并更新记忆', exact=True).click()
    page.get_by_role('button', name='确认', exact=True).click()
    wait_saved(page)
    expect(page.get_by_text('浏览器验收小说 · 已定稿 1 章 · 记忆：已同步', exact=True)).to_be_visible()
    page.get_by_role('tab', name='小说记忆').click()
    page.get_by_label('搜索历史正文', exact=True).fill('铜钥匙')
    page.get_by_role('button', name='检索', exact=True).click()
    expect(page.get_by_text('第 1 章 · 修订 1', exact=True)).to_be_visible()
    page.get_by_role('tab', name='项目管理').click()
    with page.expect_download() as download:
        page.get_by_role('button', name='导出正式章节 Markdown', exact=True).click()
    assert '铜钥匙' in Path(download.value.path()).read_text(encoding='utf-8')
    assert errors == []
    page.screenshot(path=str(directory / 'workspace.png'), full_page=True)
    log = (directory / 'server.log').read_text(encoding='utf-8')
    assert 'Traceback' not in log, log
