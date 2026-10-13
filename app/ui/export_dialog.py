from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSpinBox, QPushButton, QFileDialog, QMessageBox

from app.services.yolo_exporter import export_yolo


class ExportDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle('导出 YOLO 数据集')
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('按 group_id 划分；至少三个独立采集组。输出会自动生成新版本。'))
        row = QHBoxLayout()
        self.ratios = []
        for label, value in [('训练', 70), ('验证', 20), ('测试', 10)]:
            row.addWidget(QLabel(label + '%'))
            spin = QDoubleSpinBox(); spin.setRange(1, 98); spin.setValue(value)
            row.addWidget(spin); self.ratios.append(spin)
        layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(QLabel('随机种子'))
        self.seed = QSpinBox(); self.seed.setRange(0, 999999999); self.seed.setValue(42)
        row.addWidget(self.seed); layout.addLayout(row)
        button = QPushButton('选择输出目录并导出'); button.clicked.connect(self.run)
        layout.addWidget(button)

    def run(self):
        output = QFileDialog.getExistingDirectory(self, '选择数据集输出父目录')
        if not output: return
        try:
            result = export_yolo(self.project, output, tuple(x.value()/100 for x in self.ratios), self.seed.value())
            QMessageBox.information(self, '导出完成', str(result)); self.accept()
        except Exception as error:
            QMessageBox.critical(self, '导出失败', str(error))
