"""拾光原生桌面入口，不运行 HTTP 服务。"""
import asyncio
import inspect
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QThread, Signal, QTimer, QSaveFile, QIODevice
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QPushButton, QLineEdit, QPlainTextEdit, QSpinBox, QComboBox,
    QTabWidget, QMessageBox, QFileDialog, QDialog, QDialogButtonBox)

from agent.service import NovelService
from app.config import APP_NAME
from app.model_settings import ModelSettings, SettingsStore
from llm.client import OpenAIWriter, DemoWriter
from models.domain import Project, Memory
from storage.repository import Repository


class Job(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, repo, settings, action, parent=None):
        super().__init__(parent)
        self.repo, self.settings, self.action = repo, settings, action

    def run(self):
        async def execute():
            writer = DemoWriter() if self.settings.mode == 'demo' else OpenAIWriter(self.settings)
            try:
                result = self.action(NovelService(self.repo, writer))
                return await result if inspect.isawaitable(result) else result
            finally:
                if getattr(writer, 'client', None):
                    await writer.client.close()
        try:
            self.succeeded.emit(asyncio.run(execute()))
        except Exception as exc:
            logging.getLogger(__name__).warning('desktop job failed: %s', type(exc).__name__)
            message = str(exc)
            key = self.settings.key.get_secret_value()
            if key:
                message = message.replace(key, '[密钥已隐藏]')
            self.failed.emit(message[:1500])


def button(text, callback, layout):
    widget = QPushButton(text)
    widget.clicked.connect(lambda: callback())
    layout.addWidget(widget)
    return widget


def spin(value=1, maximum=10000000):
    widget = QSpinBox()
    widget.setRange(1, maximum)
    widget.setValue(value)
    return widget


class ApiDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('大模型 API 设置')
        self.resize(650, 440)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox(); self.mode.addItems(['openai', 'demo'])
        self.protocol = QComboBox(); self.protocol.addItems(['responses', 'chat'])
        self.base = QLineEdit(); self.model = QLineEdit(); self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.timeout = spin(120, 600); self.timeout.setMinimum(5)
        settings = owner.settings
        self.mode.setCurrentText(settings.mode); self.protocol.setCurrentText(settings.api_mode)
        self.base.setText(settings.base_url); self.model.setText(settings.model)
        self.key.setText(settings.key.get_secret_value()); self.timeout.setValue(settings.timeout)
        presets = QHBoxLayout()
        button('OpenAI 地址', lambda: self.base.setText('https://api.openai.com/v1'), presets)
        button('千问北京地址', lambda: self.base.setText('https://dashscope.aliyuncs.com/compatible-mode/v1'), presets)
        layout.addLayout(presets)
        for name, field in [('运行模式（demo 为固定示例）', self.mode), ('接口协议', self.protocol), ('API 基础地址', self.base), ('模型名称', self.model), ('API 密钥', self.key), ('超时秒数', self.timeout)]:
            form.addRow(name, field)
        layout.addLayout(form)
        hint = QLabel('Responses 需要支持结构化输出；Chat 需要支持 JSON Object。\n地址与密钥须属于同一平台及地域。保存后立即用于下一次任务。\n密钥保存到系统凭据库，不写入项目、普通配置或 Git。')
        hint.setWordWrap(True); layout.addWidget(hint)
        self.result = QLabel('测试会发送两次短请求，可能产生少量 API 费用。'); layout.addWidget(self.result)
        self.controls = QWidget(); row = QHBoxLayout(self.controls)
        button('测试连接', self.test, row); button('保存并应用', self.save, row)
        button('关闭', self.reject, row); layout.addWidget(self.controls)

    def value(self):
        return ModelSettings(mode=self.mode.currentText(), api_mode=self.protocol.currentText(), base_url=self.base.text(),
                             model=self.model.text().strip(), key=self.key.text().strip(), timeout=self.timeout.value())

    def save(self):
        try:
            value = self.value()
            self.owner.store.save(value)
            self.owner.settings = value
            self.owner.statusBar().showMessage('API 设置已保存，下一次任务立即生效')
            self.accept()
        except Exception:
            self.result.setText('保存失败：请检查地址、模型、密钥，以及系统凭据库是否可用。')

    def test(self):
        try:
            value = self.value()
        except Exception:
            self.result.setText('配置格式无效，请检查 API 地址及必填项。'); return
        async def action(service):
            await service.writer.text('rewrite', '{"request":"连接测试，只回复成功"}')
            await service.writer.structured('memory', '{"request":"JSON连接测试，summary填测试，其余数组为空"}', Memory)
            return '文本生成和结构化输出均通过（尚未保存配置）'
        self.owner.submit(action, lambda result: self.result.setText(result), settings=value, done=lambda: self.controls.setEnabled(True))
        if self.owner.job:
            self.controls.setEnabled(False)

    def reject(self):
        if self.owner.job:
            return
        super().reject()


class Window(QMainWindow):
    def __init__(self, repo, store):
        super().__init__()
        if sys.platform == 'win32' and not QFontDatabase.families():
            font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
            if font.exists(): QFontDatabase.addApplicationFont(str(font))
        self.setFont(QFont('Microsoft YaHei', 10))
        self.setStyleSheet('QPlainTextEdit,QLineEdit,QSpinBox,QComboBox {padding:5px;} QPushButton {padding:6px 12px;} QTabWidget::pane {border:1px solid #d4dce5;} QTabBar::tab {padding:10px 20px;}')
        self.repo, self.store = repo, store
        self.settings = store.load()
        self.state = None; self.job = None; self.loading = False
        self.doc_key = 'settings'; self.chapter_number = 1
        self.recovery = {}; self.dirty = False
        self.setWindowTitle(APP_NAME); self.resize(1180, 860)
        root = QWidget(); layout = QVBoxLayout(root); self.setCentralWidget(root)
        top = QHBoxLayout(); self.projects = QComboBox(); self.projects.setMinimumWidth(230)
        top.addWidget(QLabel(APP_NAME)); top.addWidget(self.projects)
        self.new_title = QLineEdit(); self.new_title.setPlaceholderText('新小说名称（必填）'); top.addWidget(self.new_title)
        button('创建项目', self.create_project, top)
        self.api_button = button('大模型 API 设置', self.api_settings, top)
        layout.addLayout(top)
        self.summary = QLabel('请选择或创建小说项目'); layout.addWidget(self.summary)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.project_form = QFormLayout(); self.project_fields = {}
        project = QWidget(); project.setLayout(self.project_form); self.tabs.addTab(project, '项目管理')
        labels = {'title':'小说名称', 'genre':'题材', 'description':'创作想法 / 简介', 'target_readers':'目标读者', 'narrative_perspective':'叙事视角', 'writing_style':'语言风格', 'target_total_words':'目标总字数', 'target_chapter_words':'单章目标字数'}
        for key, label in labels.items():
            field = spin(2000) if key.endswith('words') else QLineEdit()
            self.project_fields[key] = field; self.project_form.addRow(label, field)
        b = QPushButton('保存项目信息'); b.clicked.connect(self.save_project); self.project_form.addRow(b)
        b = QPushButton('导出正式章节 Markdown'); b.clicked.connect(self.export); self.project_form.addRow(b)
        docs = QWidget(); dl = QVBoxLayout(docs); self.tabs.addTab(docs, '设定与大纲')
        row = QHBoxLayout(); self.kind = QComboBox()
        for label, key in [('基础设定','settings'),('全书大纲','main'),('分卷大纲','volume'),('章节大纲','outline')]: self.kind.addItem(label,key)
        self.doc_index = spin(); row.addWidget(self.kind); row.addWidget(QLabel('卷号 / 章节号')); row.addWidget(self.doc_index); dl.addLayout(row)
        dl.addWidget(QLabel('生成仅保存候选。审阅后确认生效；基础设定为 JSON，请保留结构。'))
        self.idea = QLineEdit(); self.idea.setPlaceholderText('本次生成要求'); dl.addWidget(self.idea)
        self.document = QPlainTextEdit(); dl.addWidget(self.document)
        row = QHBoxLayout(); dl.addLayout(row)
        button('AI 生成 / 重新生成', self.generate_document, row)
        button('保存候选', lambda: self.save_document(False), row)
        button('确认生效', lambda: self.save_document(True), row)
        chapters = QWidget(); cl = QVBoxLayout(chapters); self.tabs.addTab(chapters, '章节创作')
        row = QHBoxLayout(); self.number = spin(); self.volume = spin(); self.chapter_title = QLineEdit(); self.target = spin(2000,20000)
        for label, widget in [('章节',self.number),('名称',self.chapter_title),('分卷',self.volume),('目标字数',self.target)]: row.addWidget(QLabel(label)); row.addWidget(widget)
        button('加载章节', self.change_chapter, row); cl.addLayout(row)
        self.outline = QPlainTextEdit(); self.outline.setReadOnly(True); self.outline.setMaximumHeight(110); cl.addWidget(self.outline)
        self.extra = QLineEdit(); self.extra.setPlaceholderText('额外创作要求'); cl.addWidget(self.extra)
        self.body = QPlainTextEdit(); cl.addWidget(self.body)
        row = QHBoxLayout(); cl.addLayout(row)
        button('保存草稿 / 章节信息', self.save_chapter, row)
        button('AI 创作 / 整章重写', self.generate_chapter, row)
        button('确认定稿并更新记忆', self.finalize, row)
        self.rewrite_instruction = QLineEdit(); self.rewrite_instruction.setPlaceholderText('选择正文段落后填写修改要求'); cl.addWidget(self.rewrite_instruction)
        row = QHBoxLayout(); cl.addLayout(row); button('修改选中段落', self.rewrite, row)
        mem = QWidget(); ml = QVBoxLayout(mem); self.tabs.addTab(mem, '小说记忆')
        self.memory_pick = QComboBox(); ml.addWidget(self.memory_pick)
        self.memory_text = QPlainTextEdit(); ml.addWidget(self.memory_text)
        row = QHBoxLayout(); ml.addLayout(row)
        button('保存记忆修订', self.save_memory, row); button('重试 / 恢复记忆同步', self.retry_memory, row)
        self.query = QLineEdit(); self.query.setPlaceholderText('历史正文关键词'); ml.addWidget(self.query)
        row = QHBoxLayout(); ml.addLayout(row); button('检索历史章节', self.search, row)
        self.history = QPlainTextEdit(); self.history.setReadOnly(True); ml.addWidget(self.history)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(1500); self.timer.timeout.connect(self.stash)
        self.document.textChanged.connect(self.edited); self.body.textChanged.connect(self.edited)
        for field in list(self.project_fields.values()) + [self.chapter_title,self.volume,self.extra,self.idea]:
            (field.valueChanged if isinstance(field,QSpinBox) else field.textChanged).connect(self.edited)
        self.projects.currentIndexChanged.connect(self.select_project)
        self.kind.currentIndexChanged.connect(self.change_document); self.doc_index.valueChanged.connect(self.change_document)
        self.memory_pick.currentIndexChanged.connect(self.load_memory)
        self.refresh_projects()

    def edited(self):
        if not self.loading and self.state:
            self.dirty = True; self.timer.start()

    def stash(self):
        if not self.state or self.loading or not self.dirty: return
        self.recovery.setdefault('documents',{})[self.doc_key] = self.document.toPlainText()
        self.recovery.setdefault('chapters',{})[str(self.chapter_number)] = dict(body=self.body.toPlainText(), title=self.chapter_title.text(), volume=self.volume.value(), extra=self.extra.text())
        self.recovery['project'] = self.project_values()
        directory = self.repo.project_path(self.state.project.project_id)
        file = QSaveFile(str(directory / 'desktop-drafts.json'))
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            self.statusBar().showMessage('自动保存失败，请检查数据目录权限'); return
        file.write(json.dumps(self.recovery,ensure_ascii=False).encode('utf-8'))
        if file.commit(): self.dirty = False; self.statusBar().showMessage('本地编辑缓存已自动保存（不会定稿或进入正式记忆）')

    def submit(self, action, success=None, settings=None, done=None):
        if self.job: self.statusBar().showMessage('请等待当前任务完成'); return
        self.stash()
        self.job = Job(self.repo,settings or self.settings,action,self)
        for i in range(self.tabs.count()): self.tabs.widget(i).setEnabled(False)
        self.projects.setEnabled(False); self.api_button.setEnabled(False)
        self.statusBar().showMessage('正在后台处理，页面仍可切换；请等待任务完成后关闭软件…')
        def completed(result):
            try:
                if success: success(result)
                else: self.refresh()
            except Exception:
                QMessageBox.warning(self,'显示结果失败','结果处理未完成，请重新打开项目。已经保存的内容会保留。')
        self.job.succeeded.connect(completed)
        self.job.failed.connect(lambda message: QMessageBox.warning(self,'操作未完成',message))
        def finished():
            self.job.deleteLater(); self.job = None
            for i in range(self.tabs.count()): self.tabs.widget(i).setEnabled(True)
            self.projects.setEnabled(True); self.api_button.setEnabled(True)
            self.statusBar().showMessage('任务已结束')
            if done: done()
        self.job.finished.connect(finished); self.job.start()

    def sync(self, action):
        if self.job or not self.state: return None
        try: return action(NovelService(self.repo,DemoWriter()))
        except Exception as exc: QMessageBox.warning(self,'无法保存',str(exc)); return None

    def confirm(self, text):
        return QMessageBox.question(self,'请确认',text) == QMessageBox.StandardButton.Yes

    def refresh_projects(self, pid=None):
        self.projects.blockSignals(True); self.projects.clear()
        for p in self.repo.list_projects(): self.projects.addItem(p.title,p.project_id)
        if pid: self.projects.setCurrentIndex(self.projects.findData(pid))
        self.projects.blockSignals(False); self.select_project()

    def create_project(self):
        if self.job: return
        if not self.new_title.text().strip(): self.statusBar().showMessage('请先填写新小说名称'); return
        try:
            self.stash(); state = self.repo.create(Project(title=self.new_title.text()))
            self.new_title.clear(); self.refresh_projects(state.project.project_id)
        except Exception as exc: QMessageBox.warning(self,'无法创建项目',str(exc))

    def select_project(self):
        self.stash(); pid = self.projects.currentData()
        self.state = self.repo.load(pid) if pid else None; self.recovery = {}
        if self.state:
            path = self.repo.project_path(pid) / 'desktop-drafts.json'
            if path.exists():
                try: self.recovery = json.loads(path.read_text(encoding='utf-8'))
                except (ValueError,OSError): self.statusBar().showMessage('编辑缓存无法读取，正式项目仍可使用')
        self.refresh()

    def refresh(self):
        if not self.state: self.tabs.setEnabled(False); return
        self.tabs.setEnabled(True); self.state = self.repo.load(self.state.project.project_id); self.loading = True
        values = self.recovery.get('project', self.state.project.model_dump())
        for key, field in self.project_fields.items():
            field.setValue(values[key]) if isinstance(field,QSpinBox) else field.setText(values[key])
        self.target.setValue(self.state.project.target_chapter_words)
        self.load_document(); self.load_chapter()
        self.memory_pick.blockSignals(True); self.memory_pick.clear()
        for number in sorted(self.state.memories): self.memory_pick.addItem(f'第{number}章 · 正式记忆',(number,False))
        for number in sorted(self.state.memory_candidates): self.memory_pick.addItem(f'第{number}章 · 待处理候选',(number,True))
        self.memory_pick.blockSignals(False); self.load_memory()
        self.summary.setText(f'{self.state.project.title} · 已定稿 {sum(bool(c.final) for c in self.state.chapters.values())} 章 · 记忆：{self.state.memory_status}  {self.state.memory_error}')
        self.loading = False

    def change_document(self):
        if self.loading: return
        self.stash(); self.load_document()

    def load_document(self):
        if not self.state: return
        kind = self.kind.currentData(); self.doc_key = kind if kind in ('settings','main') else f'{kind}:{self.doc_index.value()}'
        doc = self.state.documents.get(self.doc_key)
        self.document.blockSignals(True); self.document.setPlainText(self.recovery.get('documents',{}).get(self.doc_key, (doc.draft or doc.approved) if doc else '')); self.document.blockSignals(False)

    def change_chapter(self): self.stash(); self.load_chapter()

    def load_chapter(self):
        if not self.state: return
        self.loading = True; self.chapter_number = self.number.value(); chapter = self.state.chapters.get(self.chapter_number)
        draft = self.recovery.get('chapters',{}).get(str(self.chapter_number),{})
        self.body.setPlainText(draft.get('body',(chapter.draft or chapter.final) if chapter else ''))
        self.chapter_title.setText(draft.get('title',chapter.title if chapter else ''))
        self.volume.setValue(draft.get('volume',chapter.volume if chapter else 1)); self.extra.setText(draft.get('extra',''))
        outline = self.state.documents.get(f'outline:{self.chapter_number}')
        self.outline.setPlainText(outline.approved if outline else '请先保存章节信息，再确认本章大纲。'); self.loading = False

    def project_values(self): return {key: field.value() if isinstance(field,QSpinBox) else field.text() for key,field in self.project_fields.items()}
    def save_project(self):
        if self.state:
            result = self.sync(lambda s:s.update_project(self.state.project.project_id,self.state.version,self.project_values()))
            if result: self.recovery.pop('project',None); self.state=result; self.refresh_projects(result.project.project_id)

    def save_document(self, approve=False):
        if not self.state or (approve and not self.confirm('确认将当前文档设为正式版本？')): return
        result = self.sync(lambda s:s.save_document(self.state.project.project_id,self.state.version,self.doc_key,self.document.toPlainText(),approve))
        if result: self.recovery.get('documents',{}).pop(self.doc_key,None); self.state=result; self.dirty=True; self.stash(); self.refresh()

    def generate_document(self):
        if not self.state: return
        pid, version, key, idea = self.state.project.project_id,self.state.version,self.doc_key,self.idea.text()
        def success(result): self.recovery.get('documents',{}).pop(key,None); self.state=result; self.refresh(); self.dirty=True; self.stash()
        self.submit(lambda s:s.generate_document(pid,version,key,idea),success)

    def save_chapter(self):
        if not self.state: return None
        result = self.sync(lambda s:s.save_chapter(self.state.project.project_id,self.state.version,self.chapter_number,self.chapter_title.text(),self.volume.value(),self.body.toPlainText()))
        if result: self.state=result; self.recovery.get('chapters',{}).pop(str(self.chapter_number),None); self.refresh(); self.dirty=True; self.stash()
        return result

    def generate_chapter(self):
        if not self.save_chapter(): return
        pid, version, n, extra, target = self.state.project.project_id,self.state.version,self.chapter_number,self.extra.text(),self.target.value()
        def success(result): self.recovery.get('chapters',{}).pop(str(n),None); self.state=result; self.refresh(); self.dirty=True; self.stash()
        self.submit(lambda s:s.generate_chapter(pid,version,n,extra,target),success)

    def finalize(self):
        if not self.confirm('确认定稿当前正文并自动更新记忆？'): return
        if not self.save_chapter(): return
        pid,version,n=self.state.project.project_id,self.state.version,self.chapter_number
        self.submit(lambda s:s.finalize(pid,version,n))

    def rewrite(self):
        if not self.state: return
        cursor=self.body.textCursor(); original=self.body.toPlainText()
        if not cursor.hasSelection(): self.statusBar().showMessage('请先选择正文中的段落'); return
        # Qt 的位置是 UTF-16 单位，转换为 Python 字符索引。
        prefix=original.encode('utf-16-le')[:cursor.selectionStart()*2].decode('utf-16-le')
        selected=cursor.selectedText().replace('\u2029','\n'); start=len(prefix); end=start+len(selected)
        pid,version,n,request=self.state.project.project_id,self.state.version,self.chapter_number,self.rewrite_instruction.text()
        def success(text):
            dialog=QDialog(self); dialog.setWindowTitle('审阅段落修改建议'); dialog.resize(650,400)
            layout=QVBoxLayout(dialog); editor=QPlainTextEdit(text); layout.addWidget(editor)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); layout.addWidget(buttons)
            buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.body.setPlainText(NovelService.apply_rewrite(self.body.toPlainText(),original,start,end,editor.toPlainText()))
        self.submit(lambda s:s.rewrite(pid,version,n,original,start,end,request),success)

    def load_memory(self):
        if not self.state or not self.memory_pick.currentData(): self.memory_text.clear(); return
        n,candidate=self.memory_pick.currentData(); data=self.state.memory_candidates[n] if candidate else self.state.memories[n].data
        self.memory_text.setPlainText(data.model_dump_json(indent=2))

    def save_memory(self):
        if not self.state or not self.memory_pick.currentData(): return
        n,candidate=self.memory_pick.currentData()
        result=self.sync(lambda s:s.edit_memory(self.state.project.project_id,self.state.version,n,self.memory_text.toPlainText(),candidate))
        if result: self.state=result; self.refresh()

    def retry_memory(self):
        if self.state: self.submit(lambda s:s.retry_memory(self.state.project.project_id))

    def search(self):
        if self.state:
            hits=NovelService(self.repo,DemoWriter()).history(self.state.project.project_id,self.query.text())
            self.history.setPlainText('\n\n'.join(f'第{x["chapter"]}章：{x["text"]}' for x in hits) or '没有匹配的正式章节')

    def export(self):
        if not self.state: return
        path,_=QFileDialog.getSaveFileName(self,'导出正式章节','novel.md','Markdown (*.md)')
        if path:
            try: Path(path).write_text(self.repo.export(self.state.project.project_id),encoding='utf-8')
            except OSError: QMessageBox.warning(self,'导出失败','请检查保存位置的权限')

    def api_settings(self):
        if not self.job: ApiDialog(self).exec()

    def closeEvent(self,event):
        if self.job:
            self.statusBar().showMessage('后台任务尚未结束，请等待后再关闭，避免丢失生成结果'); event.ignore(); return
        self.stash()
        if self.dirty:
            QMessageBox.warning(self,'尚未保存','编辑缓存写入失败，请检查数据目录权限后再关闭。'); event.ignore(); return
        event.accept()


def main():
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    (root/'logs').mkdir(exist_ok=True)
    logging.basicConfig(filename=root/'logs/desktop.log',level=logging.WARNING,format='%(asctime)s %(levelname)s %(message)s')
    application=QApplication(sys.argv); application.setApplicationName(APP_NAME)
    directory=Path(os.getenv('NOVEL_DATA_DIR','projects'))
    repo=Repository(directory if directory.is_absolute() else root/directory)
    try:
        repo.acquire_instance(); window=Window(repo,SettingsStore(root)); window.show()
        application.aboutToQuit.connect(repo.close)
        if '--smoke-test' in sys.argv:
            def verified():
                path=root/'.desktop'; path.mkdir(exist_ok=True)
                (path/'smoke-test.json').write_text(json.dumps({'status':'ok','title':window.windowTitle(),'tabs':window.tabs.count()}),encoding='utf-8')
                application.quit()
            QTimer.singleShot(500,verified)
        code=application.exec()
    except Exception as exc:
        logging.error('desktop startup failed: %s',type(exc).__name__)
        QMessageBox.critical(None,'拾光无法启动','请检查数据目录是否被另一个拾光实例占用，或系统凭据库是否可用。')
        code=1
    finally: repo.close()
    sys.exit(code)


if __name__=='__main__': main()
