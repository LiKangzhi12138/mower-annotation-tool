"""Opt-in packaged acceptance smoke test; never runs during normal GUI startup."""

import json
import tempfile
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.services.merge_service import merge, plan_merge
from app.services.project_service import Project
from app.services.validation_service import inspect
from app.services.worker_package import make_package
from app.services.yolo_exporter import export_yolo
from app.ui.main_window import MainWindow
from app.utils.core import CLASS_FILE, NAMES, class_hash


def run(report_path):
    report = {'status': 'failed', 'checks': [], 'class_config_hash': None}
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        app = QApplication.instance() or QApplication([])
        report['class_config_hash'] = class_hash()
        assert CLASS_FILE.is_file() and NAMES == ('stone', 'tree', 'person', 'other_roadblock')
        report['checks'].append('bundled classes.yaml and fixed class mapping')
        with tempfile.TemporaryDirectory(prefix='Mower Annotator ', dir=report_path.parent) as temp:
            root = Path(temp)
            source = root / '中文 图片 source'
            for index in range(4):
                folder = source / f'sample_{index:03d}'
                folder.mkdir(parents=True)
                Image.new('RGB', (64, 48), (index * 45, 40, 70)).save(folder / 'same name.png')
            first = Project.create(source, root / 'worker A', 'worker_A', source_id='smoke-source')
            window = MainWindow()
            window.resize(1200, 750)
            window.show()
            window.set_project(first)
            app.processEvents()
            ids = [r['image_id'] for r in first.records]
            assert window.current_id == ids[0]
            view = window.view
            start = view.mapFromScene(QPointF(5, 6))
            end = view.mapFromScene(QPointF(38, 30))
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(view.viewport(), end)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
            app.processEvents()
            assert len(first.annotation(ids[0])['objects']) == 1
            window.mode.setCurrentIndex(1)
            view.select_object(view.objects[0]['object_id'])
            window.category.setCurrentIndex(1)
            window.change_class()
            assert first.annotation(ids[0])['objects'][0]['class_id'] == 1
            window.save_next()
            assert window.current_id == ids[1]
            window.mark_negative()
            window.save_next()
            assert window.current_id == ids[2]
            window.mark_negative()
            window.save_next()
            assert window.current_id == ids[3]
            window.close()
            restored = Project(first.output)
            assert restored.annotation(ids[0])['objects'][0]['class_id'] == 1
            assert restored.annotation(ids[1])['status'] == 'negative'
            assert restored.annotation(ids[3])['status'] == 'unreviewed'
            assert len(inspect(restored)['unreviewed']) == 1
            report['checks'].append('GUI draw, reclass, save/next, reopen, negative, unreviewed check')
            second = Project.create(source, root / 'worker B', 'worker_B', source_id='smoke-source')
            for rid in ids:
                ann = restored.annotation(rid)
                second.save_annotation(rid, ann['objects'], ann['status'])
            pack_a = make_package(restored, root / 'packages')
            pack_b = make_package(second, root / 'packages')
            plan = plan_merge([pack_a, pack_b])
            assert not plan['conflicts']
            master = Project(merge(plan, root / 'master'))
            assert len(master.records) == 4
            report['checks'].append('two Worker Packages and Master merge')
            dataset = export_yolo(master, root / 'exports', (1 / 3, 1 / 3, 1 / 3))
            labels = list((dataset / 'labels').rglob('*.txt'))
            assert len(labels) == 3
            assert sum(bool(path.read_text(encoding='utf-8')) for path in labels) == 1
            report['checks'].append('YOLO export and negative empty labels; unreviewed excluded')
            report['status'] = 'passed'
    except Exception as error:
        report['error'] = repr(error)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1
