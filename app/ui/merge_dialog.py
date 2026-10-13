from pathlib import Path
import uuid

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
                               QFileDialog, QMessageBox, QLabel, QComboBox, QTextEdit)
from app.utils.core import NAMES

from app.services.merge_service import plan_merge, merge
from app.services.worker_package import validate_package
from app.ui.image_view import ImageView


class MergeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('合并标注')
        self.resize(900, 700)
        self.paths = []
        self.plan = None
        self.resolutions = {}
        layout = QVBoxLayout(self)
        self.list = QListWidget(); layout.addWidget(self.list)
        row = QHBoxLayout()
        for label, callback in [('添加 Worker Package', self.add), ('删除已选包', self.remove),
                                ('先检查', self.check), ('生成 Master', self.run)]:
            button = QPushButton(label); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel('请添加至少两个标注包。'); layout.addWidget(self.status)
        self.conflicts = QListWidget(); layout.addWidget(self.conflicts)
        self.conflicts.currentRowChanged.connect(self.show_conflict)
        self.preview = ImageView()
        self.preview.mode = 'select'; layout.addWidget(self.preview, 2)
        self.choice = QComboBox(); layout.addWidget(self.choice)
        self.choice.currentIndexChanged.connect(self.choose)
        editor = QHBoxLayout()
        self.edit_mode = QComboBox(); self.edit_mode.addItems(['选择/编辑', '绘制'])
        self.edit_mode.currentIndexChanged.connect(lambda i: setattr(self.preview, 'mode', 'draw' if i else 'select'))
        editor.addWidget(self.edit_mode)
        self.edit_class = QComboBox()
        for i, name in enumerate(('石头', '树木', '人', '其它路障')): self.edit_class.addItem(name, i)
        self.edit_class.currentIndexChanged.connect(lambda i: setattr(self.preview, 'class_id', i))
        editor.addWidget(self.edit_class)
        for title, fn in [('修改类别', self.reclass), ('删除框', self.delete_box), ('采用手动修正', self.use_manual)]:
            button = QPushButton(title); button.clicked.connect(fn); editor.addWidget(button)
        layout.addLayout(editor)
        self.manual_status = QComboBox(); self.manual_status.addItems(['positive', 'negative', 'unreviewed', 'uncertain', 'exclude'])
        layout.addWidget(self.manual_status)
        self.details = QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(100); layout.addWidget(self.details)

    def add(self):
        path = QFileDialog.getExistingDirectory(self, '选择 Worker Package 目录')
        if not path or path in self.paths: return
        try:
            meta, records, anns = validate_package(path)
            completed = sum(a['status'] in ('positive', 'negative') for a in anns.values())
            self.paths.append(path)
            self.list.addItem(f"{meta['worker_id']}  图片 {len(records)}  完成率 {completed/max(1,len(records))*100:.1f}%  {path}")
            self.plan = None
        except Exception as error:
            QMessageBox.critical(self, '包校验失败', str(error))

    def remove(self):
        row = self.list.currentRow()
        if row >= 0:
            self.paths.pop(row); self.list.takeItem(row); self.plan = None

    def check(self):
        try:
            self.plan = plan_merge(self.paths)
            self.resolutions = {}
            self.conflicts.clear()
            for c in self.plan['conflicts']:
                self.conflicts.addItem(f"{c['type']} | {c['image_id']} | {', '.join(c['workers'])}")
            self.status.setText(f"检查完成：{len(self.plan['by_hash'])} 张唯一图片，{len(self.plan['conflicts'])} 个冲突。请逐一选择标注来源。")
        except Exception as error:
            QMessageBox.critical(self, '检查失败', str(error))

    def show_conflict(self, row):
        if not self.plan or row < 0: return
        c = self.plan['conflicts'][row]
        self.choice.blockSignals(True); self.choice.clear(); self.choice.addItem('暂不处理', None)
        items = self.conflict_items(c)
        if items:
            for item in items:
                self.choice.addItem(f"保留 {item['package']['worker_id']} ({item['package']['package_id'][:8]})", item['package']['package_id'])
            item = items[0]
            colors = ('#ff1744', '#00b0ff', '#76ff03', '#ffea00', '#d500f9')
            overlay = []
            for index, source_item in enumerate(items):
                for obj in source_item['annotation']['objects']:
                    overlay.append(dict(obj, object_id=str(uuid.uuid4()), bbox=list(obj['bbox']),
                                        display_label=f"{source_item['package']['worker_id']}: {obj['class_name']}",
                                        display_color=colors[index % len(colors)]))
            self.preview.load(item['root'] / item['record']['package_image_path'], overlay)
            self.preview.mode = 'select'
            self.edit_mode.setCurrentIndex(0)
        self.details.setPlainText(str(c['difference']))
        saved = self.resolutions.get(c['key'])
        idx = self.choice.findData(saved['package_id'] if isinstance(saved, dict) else saved)
        self.choice.setCurrentIndex(max(0, idx)); self.choice.blockSignals(False)

    def conflict_items(self, conflict):
        if conflict['key'] in self.plan['by_hash']:
            return self.plan['by_hash'][conflict['key']]
        source_id, relative = conflict['key'][7:].split('|', 1)
        return [x for group in self.plan['by_hash'].values() for x in group
                if x['record']['source_id'] == source_id and x['record']['relative_path'] == relative]

    def choose(self):
        row = self.conflicts.currentRow()
        if not self.plan or row < 0: return
        key = self.plan['conflicts'][row]['key']
        value = self.choice.currentData()
        if value:
            self.resolutions[key] = value
            item = next(x for x in self.conflict_items(self.plan['conflicts'][row]) if x['package']['package_id'] == value)
            self.preview.load(item['root'] / item['record']['package_image_path'],
                              [dict(o, bbox=list(o['bbox'])) for o in item['annotation']['objects']])
            self.manual_status.setCurrentText(item['annotation']['status'])
        else: self.resolutions.pop(key, None)

    def reclass(self):
        oid = self.preview.selected_id()
        if not oid: return
        obj = next(o for o in self.preview.objects if o['object_id'] == oid)
        obj['class_id'] = self.edit_class.currentIndex(); obj['class_name'] = NAMES[obj['class_id']]
        self.preview.items_by_id[oid].refresh()

    def delete_box(self):
        oid = self.preview.selected_id()
        if not oid: return
        self.preview.objects[:] = [o for o in self.preview.objects if o['object_id'] != oid]
        self.preview.scene().removeItem(self.preview.items_by_id.pop(oid))

    def use_manual(self):
        row = self.conflicts.currentRow()
        if row < 0 or not self.choice.currentData():
            QMessageBox.warning(self, '冲突', '请先选择一份标注来源'); return
        conflict = self.plan['conflicts'][row]
        chosen = next(x for x in self.conflict_items(conflict) if x['package']['package_id'] == self.choice.currentData())
        ann = dict(chosen['annotation'], objects=[dict(x, bbox=list(x['bbox'])) for x in self.preview.objects],
                   status=self.manual_status.currentText())
        self.resolutions[conflict['key']] = dict(package_id=self.choice.currentData(), annotation=ann)
        self.status.setText(f"已记录手动修正：{conflict['image_id']}")

    def run(self):
        if not self.plan: self.check()
        if not self.plan: return
        path = QFileDialog.getExistingDirectory(self, '选择空的 Master 输出目录')
        if not path: return
        try:
            result = merge(self.plan, path, self.resolutions)
            QMessageBox.information(self, '合并成功', f'Master 项目：{result}')
            self.result_path = result
            self.accept()
        except Exception as error:
            QMessageBox.critical(self, '合并失败', str(error))
