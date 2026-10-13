from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QListWidget, QComboBox, QSplitter, QFileDialog,
                               QMessageBox, QLineEdit, QProgressBar, QInputDialog, QTextEdit,
                               QDialog, QFormLayout, QDialogButtonBox)

from app.services.project_service import Project
from app.services.worker_package import make_package
from app.ui.image_view import ImageView
from app.ui.quality_dialog import QualityDialog
from app.ui.merge_dialog import MergeDialog
from app.ui.export_dialog import ExportDialog
from app.utils.core import NAMES, classes


class ScanThread(QThread):
    progress = Signal(int, int)
    finishedProject = Signal(object, object)

    def __init__(self, source, output, worker, source_id):
        super().__init__()
        self.source, self.output, self.worker, self.source_id = source, output, worker, source_id

    def run(self):
        try:
            project = Project.create(self.source, self.output, self.worker,
                                     lambda i, n: self.progress.emit(i, n), self.source_id)
            self.finishedProject.emit(project, None)
        except Exception as error:
            self.finishedProject.emit(None, str(error))


class RescanThread(QThread):
    progress = Signal(int, int)
    completed = Signal(object, object)

    def __init__(self, project):
        super().__init__()
        self.project = project

    def run(self):
        try:
            errors = self.project.rescan(lambda i, n: self.progress.emit(i, n))
            self.completed.emit(errors, None)
        except Exception as error:
            self.completed.emit(None, str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('智能割草机视觉数据标注工具')
        self.resize(1500, 900)
        self.settings = QSettings('MowerAnnotator', 'MowerAnnotator')
        self.source = self.settings.value('source', '')
        self.output = self.settings.value('output', '')
        self.project = None
        self.current_id = None
        self.filtered = []
        self.busy = False
        root = QWidget(); self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        toolbar = QHBoxLayout(); outer.addLayout(toolbar)
        for title, callback in [('选择输入目录', self.choose_source), ('选择输出目录', self.choose_output),
                                ('新建项目', self.create_project), ('打开已有标注项目', self.open_project),
                                ('重新扫描', self.rescan), ('保存', self.save), ('标注检查', self.quality),
                                ('生成便携标注包', self.package), ('合并标注', self.merge),
                                ('导出 YOLO', self.export), ('快捷键说明', self.help)]:
            button = QPushButton(title); button.clicked.connect(callback); toolbar.addWidget(button)
        self.paths = QLabel(); outer.addWidget(self.paths); self.update_paths()
        self.progress = QProgressBar(); self.progress.hide(); outer.addWidget(self.progress)
        splitter = QSplitter(Qt.Orientation.Horizontal); outer.addWidget(splitter, 1)
        left = QWidget(); ll = QVBoxLayout(left)
        self.filter = QComboBox(); self.filter.addItems(['全部', 'unreviewed', 'positive', 'negative', 'uncertain', 'exclude'])
        self.filter.currentIndexChanged.connect(self.refresh_list); ll.addWidget(self.filter)
        self.image_list = QListWidget(); self.image_list.currentRowChanged.connect(self.list_changed); ll.addWidget(self.image_list)
        self.count = QLabel('0/0'); ll.addWidget(self.count)
        splitter.addWidget(left)
        center = QWidget(); cl = QVBoxLayout(center)
        nav = QHBoxLayout()
        for label, callback in [('上一张', self.previous), ('下一张', self.next), ('下一张未标注', self.next_unreviewed),
                                ('适应窗口', lambda: self.view.fit()), ('实际比例', lambda: self.view.actual())]:
            button = QPushButton(label); button.clicked.connect(callback); nav.addWidget(button)
        cl.addLayout(nav)
        self.view = ImageView(); self.view.objectsChanged.connect(self.objects_changed)
        self.view.selectedObject.connect(self.selection_changed); cl.addWidget(self.view)
        splitter.addWidget(center)
        right = QWidget(); rl = QVBoxLayout(right)
        self.mode = QComboBox(); self.mode.addItems(['绘制', '选择/编辑']); self.mode.currentIndexChanged.connect(self.mode_changed)
        rl.addWidget(QLabel('操作模式')); rl.addWidget(self.mode)
        self.category = QComboBox()
        for c in classes()['classes']: self.category.addItem(f"{c['id']+1}  {c['zh']} ({c['name']})", c['id'])
        self.category.currentIndexChanged.connect(self.category_changed)
        rl.addWidget(QLabel('类别')); rl.addWidget(self.category)
        self.object_list = QListWidget(); self.object_list.currentRowChanged.connect(self.object_selected)
        rl.addWidget(QLabel('目标框')); rl.addWidget(self.object_list)
        row = QHBoxLayout()
        for title, fn in [('修改选中框类别', self.change_class), ('删除选中框', self.delete_selected)]:
            button = QPushButton(title); button.clicked.connect(fn); row.addWidget(button)
        rl.addLayout(row)
        self.status_combo = QComboBox(); self.status_combo.addItems(['unreviewed', 'positive', 'negative', 'uncertain', 'exclude'])
        self.status_combo.currentTextChanged.connect(self.status_changed)
        rl.addWidget(QLabel('当前图片状态')); rl.addWidget(self.status_combo)
        negative = QPushButton('确认无目标 (N)'); negative.clicked.connect(self.mark_negative); rl.addWidget(negative)
        self.meta = QLabel(); self.meta.setWordWrap(True); rl.addWidget(self.meta)
        group_button = QPushButton('设置当前图片 group_id'); group_button.clicked.connect(self.set_group)
        rl.addWidget(group_button)
        splitter.addWidget(right); splitter.setSizes([290, 950, 260])
        self.bottom = QLabel('请选择输入和输出目录，或打开已有项目。'); outer.addWidget(self.bottom)
        self.shortcuts()

    def shortcuts(self):
        commands = {'1': lambda: self.category.setCurrentIndex(0), '2': lambda: self.category.setCurrentIndex(1),
                    '3': lambda: self.category.setCurrentIndex(2), '4': lambda: self.category.setCurrentIndex(3),
                    'Space': self.save_next, 'Left': self.previous, 'Right': self.next, 'Ctrl+S': self.save,
                    'Delete': self.delete_selected, 'F': self.view.fit, 'N': self.mark_negative,
                    'U': self.next_unreviewed, 'Escape': self.view.cancel,
                    'D': lambda: self.mode.setCurrentIndex(0), 'V': lambda: self.mode.setCurrentIndex(1)}
        self._shortcuts = []
        for key, action in commands.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(lambda fn=action: self.shortcut_action(fn))
            self._shortcuts.append(shortcut)

    def shortcut_action(self, action):
        from PySide6.QtWidgets import QApplication, QAbstractSpinBox
        if isinstance(QApplication.focusWidget(), (QLineEdit, QTextEdit, QAbstractSpinBox)):
            return
        action()

    def update_paths(self):
        self.paths.setText(f'输入：{self.source or "未选择"}    输出：{self.output or "未选择"}')

    def choose_source(self):
        path = QFileDialog.getExistingDirectory(self, '选择输入图片目录', self.source)
        if path:
            self.source = path; self.settings.setValue('source', path); self.update_paths()

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, '选择输出标注目录', self.output)
        if path:
            self.output = path; self.settings.setValue('output', path); self.update_paths()

    def create_project(self):
        if not self.source or not self.output:
            QMessageBox.warning(self, '路径', '请先选择输入和输出目录'); return
        dialog = QDialog(self); dialog.setWindowTitle('新建标注项目')
        form = QFormLayout(dialog)
        worker_edit = QLineEdit('worker_A')
        source_edit = QLineEdit(Path(self.source).name)
        form.addRow('标注人员 ID', worker_edit)
        form.addRow('数据来源 ID（多人标注同一批图时须相同）', source_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        worker, source_id = worker_edit.text().strip(), source_edit.text().strip()
        if not worker or not source_id:
            QMessageBox.warning(self, '项目 ID', '标注人员 ID 和数据来源 ID 都不能为空'); return
        if self.busy: return
        self.busy = True; self.progress.show(); self.progress.setValue(0)
        self.scan_thread = ScanThread(self.source, self.output, worker, source_id)
        self.scan_thread.progress.connect(lambda i, n: (self.progress.setMaximum(max(1,n)), self.progress.setValue(i)))
        self.scan_thread.finishedProject.connect(self.scan_done)
        self.scan_thread.start()

    def scan_done(self, project, error):
        self.busy = False; self.progress.hide()
        if error:
            QMessageBox.critical(self, '导入失败', error); return
        self.set_project(project)
        if project.data.get('scan_errors'):
            QMessageBox.warning(self, '部分图片无法解码', '\n'.join(project.data['scan_errors'][:20]))

    def open_project(self, path=None):
        if not path or isinstance(path, bool): path = QFileDialog.getExistingDirectory(self, '打开已有标注项目', self.output)
        if not path: return
        try:
            self.save()
            project = Project(path)
            self.set_project(project)
            self.output = str(project.output); self.source = project.data.get('source_root', '')
            self.settings.setValue('output', self.output); self.update_paths()
        except Exception as error:
            QMessageBox.critical(self, '打开失败', str(error))

    def set_project(self, project):
        self.project = project; self.current_id = None
        self.refresh_list()
        self.bottom.setText(f'项目：{project.output}，图片 {len(project.records)} 张')
        if project.load_errors:
            QMessageBox.warning(self, '标注读取异常', '\n'.join(project.load_errors[:20]))

    def refresh_list(self):
        if not self.project: return
        current = self.current_id
        selected = self.filter.currentText()
        self.filtered = [r['image_id'] for r in self.project.records if selected == '全部' or r['status'] == selected]
        self.image_list.blockSignals(True); self.image_list.clear()
        for rid in self.filtered:
            r = self.project.by_id[rid]
            self.image_list.addItem(f"[{r['status']}] {r['relative_path']}")
        self.image_list.blockSignals(False)
        if current in self.filtered:
            self.image_list.setCurrentRow(self.filtered.index(current))
        elif self.filtered:
            self.image_list.setCurrentRow(0)
        else:
            self.current_id = None; self.view.scene().clear(); self.count.setText('0/0')

    def list_changed(self, row):
        if row >= 0 and row < len(self.filtered): self.goto(self.filtered[row])

    def goto(self, rid):
        if not self.project or rid not in self.project.by_id: return
        if rid == self.current_id: return
        if self.current_id and not self.save(): return
        try:
            record = self.project.by_id[rid]
            ann = self.project.annotation(rid)
            self.view.load(self.project.image_path(record), ann['objects'])
            self.current_id = rid
            self.status_combo.blockSignals(True)
            self.status_combo.setCurrentText(ann['status'])
            self.status_combo.blockSignals(False)
            self.refresh_objects()
            self.meta.setText(f"尺寸：{record['image_width']} × {record['image_height']}\n格式：{Path(record['original_filename']).suffix}\n"
                              f"SHA256：{record['image_sha256'][:16]}…\n分组：{record['group_id'] or '未确定'}")
            self.count.setText(f'{self.project.records.index(record)+1}/{len(self.project.records)}')
            self.bottom.setText(f"{record['relative_path']}  |  {ann['status']}")
            if rid in self.filtered and self.image_list.currentRow() != self.filtered.index(rid):
                self.image_list.blockSignals(True); self.image_list.setCurrentRow(self.filtered.index(rid)); self.image_list.blockSignals(False)
        except Exception as error:
            QMessageBox.critical(self, '图片读取失败', f'{rid}: {error}')

    def refresh_objects(self):
        self.object_list.blockSignals(True); self.object_list.clear()
        for obj in self.view.objects:
            self.object_list.addItem(f"{classes()['classes'][obj['class_id']]['zh']}  {', '.join(f'{v:.1f}' for v in obj['bbox'])}")
        self.object_list.blockSignals(False)

    def objects_changed(self):
        if not self.current_id: return
        if self.view.objects: self.status_combo.setCurrentText('positive')
        elif self.status_combo.currentText() == 'positive': self.status_combo.setCurrentText('unreviewed')
        self.refresh_objects(); self.save()

    def save(self):
        if not self.project or not self.current_id: return True
        try:
            self.project.save_annotation(self.current_id, self.view.objects, self.status_combo.currentText())
            if self.current_id in self.filtered:
                row = self.filtered.index(self.current_id)
                self.image_list.item(row).setText(f"[{self.status_combo.currentText()}] {self.project.by_id[self.current_id]['relative_path']}")
            self.bottom.setText(f'已保存：{self.project.by_id[self.current_id]["relative_path"]}  |  {self.status_combo.currentText()}')
            return True
        except Exception as error:
            QMessageBox.critical(self, '保存失败', str(error)); return False

    def _move(self, step):
        if not self.current_id or self.busy: return
        ids = [r['image_id'] for r in self.project.records]
        position = ids.index(self.current_id) + step
        if not 0 <= position < len(ids):
            self.bottom.setText('已到第一张或最后一张图片'); return
        self.goto(ids[position])

    def previous(self): self._move(-1)
    def next(self): self._move(1)
    def save_next(self):
        if not self.busy and self.save(): self.next()

    def next_unreviewed(self):
        if not self.project: return
        ids = [r['image_id'] for r in self.project.records]
        start = ids.index(self.current_id)+1 if self.current_id in ids else 0
        for rid in ids[start:] + ids[:start]:
            if self.project.by_id[rid]['status'] == 'unreviewed':
                self.goto(rid); return
        self.bottom.setText('没有未标注图片')

    def mode_changed(self, index): self.view.mode = 'draw' if index == 0 else 'select'
    def category_changed(self, index): self.view.class_id = index

    def object_selected(self, row):
        if 0 <= row < len(self.view.objects): self.view.select_object(self.view.objects[row]['object_id'])

    def selection_changed(self, oid):
        if oid:
            for i, obj in enumerate(self.view.objects):
                if obj['object_id'] == oid:
                    self.object_list.blockSignals(True); self.object_list.setCurrentRow(i); self.object_list.blockSignals(False)
                    break

    def change_class(self):
        oid = self.view.selected_id()
        if not oid: return
        obj = next(o for o in self.view.objects if o['object_id'] == oid)
        obj['class_id'] = self.category.currentIndex(); obj['class_name'] = NAMES[obj['class_id']]
        self.view.items_by_id[oid].refresh(); self.objects_changed()

    def delete_selected(self):
        oid = self.view.selected_id()
        if not oid: return
        self.view.objects[:] = [o for o in self.view.objects if o['object_id'] != oid]
        self.view.scene().removeItem(self.view.items_by_id.pop(oid)); self.objects_changed()

    def status_changed(self, status):
        if not self.current_id: return
        if status == 'positive' and not self.view.objects:
            QMessageBox.warning(self, '状态错误', 'positive 需要至少一个目标框')
            self.status_combo.setCurrentText('unreviewed'); return
        if status in ('negative', 'unreviewed', 'exclude') and self.view.objects:
            QMessageBox.warning(self, '状态错误', f'{status} 不能包含目标框')
            self.status_combo.setCurrentText('positive'); return
        self.save()

    def mark_negative(self):
        if not self.current_id: return
        if self.view.objects:
            QMessageBox.warning(self, '无法标记', '请先删除目标框'); return
        self.status_combo.setCurrentText('negative')

    def set_group(self):
        if not self.current_id or not self.project: return
        record = self.project.by_id[self.current_id]
        value, ok = QInputDialog.getText(self, '采集分组',
                                         '填写采集会话/视频/Snapshot 的组 ID；同一组图片应使用完全相同的值：',
                                         text=record.get('group_id') or '')
        if not ok: return
        if not value.strip():
            QMessageBox.warning(self, '分组', 'group_id 不能为空'); return
        record['group_id'] = value.strip()
        try:
            self.project.save_index()
            self.meta.setText(self.meta.text().rsplit('分组：', 1)[0] + '分组：' + value.strip())
        except Exception as error:
            QMessageBox.critical(self, '分组保存失败', str(error))

    def rescan(self):
        if not self.project or self.project.data['project_type'] == 'master' or self.busy: return
        if not self.save(): return
        self.busy = True; self.progress.show(); self.progress.setValue(0)
        self.scan_thread = RescanThread(self.project)
        self.scan_thread.progress.connect(lambda i, n: (self.progress.setMaximum(max(1,n)), self.progress.setValue(i)))
        self.scan_thread.completed.connect(self.rescan_done)
        self.scan_thread.start()

    def rescan_done(self, errors, failure):
        self.busy = False; self.progress.hide()
        if failure:
            QMessageBox.critical(self, '重新扫描失败', failure); return
        self.refresh_list()
        QMessageBox.information(self, '重新扫描完成', f"图片 {len(self.project.records)} 张。\n" + '\n'.join(errors[:10]))

    def quality(self):
        if not self.project: return
        self.save(); dialog = QualityDialog(self.project, self)
        dialog.openImage.connect(self.goto)
        dialog.onlyUnreviewed.connect(lambda: self.filter.setCurrentText('unreviewed'))
        dialog.exec()

    def package(self):
        if not self.project or self.project.data['project_type'] != 'worker': return
        if not self.save(): return
        parent = QFileDialog.getExistingDirectory(self, '选择便携包输出父目录')
        if not parent: return
        try:
            result = make_package(self.project, parent)
            QMessageBox.information(self, '打包完成', str(result))
        except Exception as error: QMessageBox.critical(self, '打包失败', str(error))

    def merge(self):
        dialog = MergeDialog(self)
        if dialog.exec() and hasattr(dialog, 'result_path'):
            self.open_project(dialog.result_path)

    def export(self):
        if self.project and self.save(): ExportDialog(self.project, self).exec()

    def help(self):
        QMessageBox.information(self, '快捷键', '1–4 类别；D 绘制；V 选择/编辑；Space 保存并下一张；←/→ 导航；\n'
                                'Ctrl+S 保存；Delete 删除；F 适应窗口；N 确认无目标；U 下一张未标注；Esc 取消。')

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.warning(self, '任务进行中', '请等待扫描完成后再关闭')
            event.ignore(); return
        if self.save(): event.accept()
        else: event.ignore()
