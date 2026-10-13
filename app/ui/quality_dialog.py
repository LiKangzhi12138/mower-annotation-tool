import csv
import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTabWidget, QListWidget,
                               QPushButton, QFileDialog, QHBoxLayout, QMessageBox)

from app.services.validation_service import inspect


class QualityDialog(QDialog):
    openImage = Signal(str)
    onlyUnreviewed = Signal()

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle('标注检查')
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        tabs = QTabWidget()
        self.unreviewed = QListWidget()
        self.issues = QListWidget()
        tabs.addTab(self.unreviewed, '未标注')
        tabs.addTab(self.issues, '检查问题')
        layout.addWidget(tabs)
        row = QHBoxLayout()
        for title, fn in [('仅显示未标注', self.filter), ('下一张未标注', self.next_unreviewed),
                          ('运行完整检查', self.refresh), ('导出检查报告', self.export)]:
            button = QPushButton(title)
            button.clicked.connect(fn)
            row.addWidget(button)
        layout.addLayout(row)
        self.unreviewed.itemDoubleClicked.connect(lambda item: self.openImage.emit(item.data(256)))
        self.issues.itemDoubleClicked.connect(lambda item: self.openImage.emit(item.data(256)))
        self.refresh()

    def refresh(self):
        self.report = inspect(self.project, verify_hash=True)
        s = self.report['stats']
        categories = '  '.join(f'{name}: {s.get("class_"+str(i), 0)}' for i, name in enumerate(('石头', '树木', '人', '其它路障')))
        self.summary.setText(f"总数 {s['total']}  已完成 {s['completed']}  未标注 {s.get('unreviewed',0)}  "
                             f"positive {s.get('positive',0)}  negative {s.get('negative',0)}  "
                             f"uncertain {s.get('uncertain',0)}  exclude {s.get('exclude',0)}  "
                             f"完成率 {100*s['completed']/max(1,s['total']):.1f}%\n{categories}")
        self.unreviewed.clear(); self.issues.clear()
        for r in self.report['unreviewed']:
            self.unreviewed.addItem(f"{r['relative_path']}  [unreviewed]")
            self.unreviewed.item(self.unreviewed.count()-1).setData(256, r['image_id'])
        for issue in self.report['issues']:
            self.issues.addItem(f"{issue['path']}: {issue['issue']}")
            self.issues.item(self.issues.count()-1).setData(256, issue['image_id'])

    def filter(self):
        self.onlyUnreviewed.emit()
        self.accept()

    def next_unreviewed(self):
        if self.report['unreviewed']:
            self.openImage.emit(self.report['unreviewed'][0]['image_id'])
            self.accept()
        else:
            QMessageBox.information(self, '检查', '没有未标注图片')

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出检查报告', str(self.project.output / 'quality_report.json'), 'JSON (*.json);;CSV (*.csv)')
        if not path:
            return
        if path.lower().endswith('.csv'):
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=['image_id', 'path', 'issue'])
                writer.writeheader(); writer.writerows(self.report['issues'])
        else:
            Path(path).write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')
