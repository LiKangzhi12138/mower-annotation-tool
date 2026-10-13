import json
import uuid
from pathlib import Path

import pytest
import yaml
from PIL import Image

from app.services.image_scanner import scan, infer_group
from app.services.project_service import Project
from app.services.validation_service import inspect
from app.services.worker_package import make_package, validate_package
from app.services.merge_service import plan_merge, merge
from app.services.split_service import split_groups
from app.services.yolo_exporter import export_yolo
from app.utils.core import atomic_json, read_json, bbox_valid, yolo_box


def source(tmp_path, groups=3):
    root = tmp_path / 'source'
    for i in range(groups):
        folder = root / f'group_{i}'
        folder.mkdir(parents=True)
        Image.new('RGB', (40, 20), (i * 50, 20, 20)).save(folder / 'same.png')
    return root


def obj(cls=0, box=(1, 2, 20, 10)):
    names = ('stone', 'tree', 'person', 'other_roadblock')
    return dict(object_id=str(uuid.uuid4()), class_id=cls, class_name=names[cls], bbox=list(box))


def project(tmp_path, name='out'):
    return Project.create(source(tmp_path), tmp_path / name)


def test_scan_same_names_and_stability(tmp_path):
    assert infer_group('airport_mower_samples/sample_000030/images/image_00.png') == 'airport_mower_samples/sample_000030'
    assert infer_group('unknown/images/a.png') is None
    root = source(tmp_path)
    a, errors = scan(root, 'source-1')
    b, _ = scan(root, 'source-1')
    assert not errors and len(a) == 3
    assert len({r['image_id'] for r in a}) == 3
    assert [r['image_id'] for r in a] == [r['image_id'] for r in b]


def test_shared_source_id_across_workers(tmp_path):
    root = source(tmp_path)
    a = Project.create(root, tmp_path / 'worker_a', 'worker_A', source_id='mower-capture-001')
    b = Project.create(root, tmp_path / 'worker_b', 'worker_B', source_id='mower-capture-001')
    assert [r['image_id'] for r in a.records] == [r['image_id'] for r in b.records]


def test_bbox_and_status(tmp_path):
    p = project(tmp_path)
    rid = p.records[0]['image_id']
    assert bbox_valid([0, 0, 40, 20], 40, 20)
    assert not bbox_valid([0, 0, 41, 20], 40, 20)
    assert yolo_box([0, 0, 40, 20], 40, 20) == (0.5, 0.5, 1, 1)
    with pytest.raises(ValueError): p.save_annotation(rid, [], 'positive')
    with pytest.raises(ValueError): p.save_annotation(rid, [obj()], 'negative')
    p.save_annotation(rid, [], 'negative')
    assert Project(p.output).annotation(rid)['status'] == 'negative'


def test_atomic_recovery(tmp_path):
    path = tmp_path / 'x.json'
    atomic_json(path, {'v': 1}); atomic_json(path, {'v': 2})
    path.write_text('{broken', encoding='utf-8')
    assert read_json(path) == {'v': 1}


def test_interrupted_temp_recovery(tmp_path):
    path = tmp_path / 'annotation.json'
    (tmp_path / 'annotation.json.abcd.tmp').write_text('{"ok": true}', encoding='utf-8')
    assert read_json(path) == {'ok': True}
    assert path.exists()


def test_package_merge_and_duplicate(tmp_path):
    p = project(tmp_path)
    rid = p.records[0]['image_id']
    p.save_annotation(rid, [obj()], 'positive')
    a = make_package(p, tmp_path / 'packages')
    b = make_package(p, tmp_path / 'packages')
    assert a != b
    assert validate_package(a)[0]['image_count'] == 3
    plan = plan_merge([a, b])
    assert not plan['conflicts'] and len(plan['by_hash']) == 3
    (tmp_path / 'master').mkdir()
    master = merge(plan, tmp_path / 'master')
    reopened = Project(master)
    assert len(reopened.records) == 3
    ann = reopened.annotation(rid)
    assert len(ann['provenance']) == 2
    assert len(ann['objects'][0]['provenance']) == 2
    reopened.save_annotation(rid, ann['objects'], 'positive')
    assert len(Project(master).annotation(rid)['objects'][0]['provenance']) == 2


def test_three_independent_workers_same_content(tmp_path):
    root = source(tmp_path)
    packages = []
    for worker in ('worker_A', 'worker_B', 'worker_C'):
        p = Project.create(root, tmp_path / worker, worker)
        packages.append(make_package(p, tmp_path / 'packs'))
    plan = plan_merge(packages)
    assert len(plan['by_hash']) == 3
    assert not plan['conflicts']
    master = Project(merge(plan, tmp_path / 'master'))
    assert len(master.records) == 3
    assert all(len(master.annotation(r['image_id'])['provenance']) == 3 for r in master.records)


def test_conflict_and_class_rejection(tmp_path):
    p = project(tmp_path)
    rid = p.records[0]['image_id']
    p.save_annotation(rid, [obj(0)], 'positive')
    a = make_package(p, tmp_path / 'packs')
    p.save_annotation(rid, [obj(1)], 'positive')
    b = make_package(p, tmp_path / 'packs')
    plan = plan_merge([a, b])
    assert plan['conflicts']
    with pytest.raises(ValueError): merge(plan, tmp_path / 'master')
    digest = p.records[0]['image_sha256']
    master = merge(plan, tmp_path / 'master', {digest: validate_package(a)[0]['package_id']})
    assert Project(master).annotation(rid)['objects'][0]['class_id'] == 0
    cfg = b / 'classes.yaml'
    cfg.write_text(cfg.read_text(encoding='utf-8').replace('stone', 'rock'), encoding='utf-8')
    with pytest.raises(ValueError): plan_merge([a, b])


def test_manual_conflict_resolution(tmp_path):
    p = project(tmp_path)
    rid = p.records[0]['image_id']
    p.save_annotation(rid, [obj(0)], 'positive')
    a = make_package(p, tmp_path / 'packs')
    p.save_annotation(rid, [obj(1)], 'positive')
    b = make_package(p, tmp_path / 'packs')
    plan = plan_merge([a, b])
    digest = p.records[0]['image_sha256']
    corrected = dict(p.annotation(rid), objects=[obj(2)])
    selection = dict(package_id=validate_package(a)[0]['package_id'], annotation=corrected)
    master = Project(merge(plan, tmp_path / 'master', {digest: selection}))
    assert master.annotation(rid)['objects'][0]['class_id'] == 2


def test_missing_or_changed_image(tmp_path):
    p = project(tmp_path)
    a = make_package(p, tmp_path / 'packs')
    meta, records, _ = validate_package(a)
    path = a / records[0]['package_image_path']
    path.write_bytes(b'changed')
    with pytest.raises(ValueError): validate_package(a)


def test_same_source_path_changed_hash_conflict(tmp_path):
    p = project(tmp_path)
    a = make_package(p, tmp_path / 'packs')
    b = make_package(p, tmp_path / 'packs')
    meta, records, _ = validate_package(b)
    image = b / records[0]['package_image_path']
    Image.new('RGB', (40, 20), (251, 12, 3)).save(image)
    digest = __import__('hashlib').sha256(image.read_bytes()).hexdigest()
    manifest = b / 'manifests' / 'images.csv'
    import csv
    with manifest.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    rows[0]['image_sha256'] = digest
    with manifest.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    plan = plan_merge([a, b])
    conflict = next(x for x in plan['conflicts'] if x['type'] == '同一来源路径内容不同')
    with pytest.raises(ValueError): merge(plan, tmp_path / 'master')
    result = merge(plan, tmp_path / 'master', {conflict['key']: validate_package(a)[0]['package_id']})
    assert len(Project(result).records) == 3


def test_rescan_preserves_annotations_and_detects_changes(tmp_path):
    p = project(tmp_path)
    rid = p.records[0]['image_id']
    p.save_annotation(rid, [obj()], 'positive')
    image = Path(p.records[0]['source_root']) / p.records[0]['relative_path']
    Image.new('RGB', (40, 20), (255, 0, 0)).save(image)
    errors = p.rescan()
    assert any('内容变化' in e for e in errors)
    assert p.by_id[rid]['status'] == 'positive'
    assert p.annotation(rid)['objects'][0]['class_id'] == 0
    assert any('SHA256' in x['issue'] for x in inspect(p, verify_hash=True)['issues'])


def test_yolo_export_and_group_split(tmp_path):
    p = project(tmp_path)
    p.save_annotation(p.records[0]['image_id'], [obj()], 'positive')
    p.save_annotation(p.records[1]['image_id'], [], 'negative')
    with pytest.raises(ValueError): export_yolo(p, tmp_path / 'exports')
    p.save_annotation(p.records[2]['image_id'], [], 'negative')
    with pytest.raises(ValueError): export_yolo(p, tmp_path / 'exports')
    ratios = (1/3, 1/3, 1/3)
    result = export_yolo(p, tmp_path / 'exports', ratios)
    data = yaml.safe_load((result / 'data.yaml').read_text(encoding='utf-8'))
    assert data['names'] == ['stone', 'tree', 'person', 'other_roadblock']
    labels = list((result / 'labels').rglob('*.txt'))
    assert len(labels) == 3 and sum(bool(x.read_text()) for x in labels) == 1
    assert len(list((result / 'images').rglob('*.png'))) == 3
    assigned = split_groups(p.records, ratios, seed=42)
    assert assigned == split_groups(p.records, ratios, seed=42)
    assert len(set(assigned.values())) == 3
    p.records[0]['group_id'] = None
    with pytest.raises(ValueError): split_groups(p.records)


def test_quality_missing_duplicate_and_unreviewed(tmp_path):
    p = project(tmp_path)
    assert len(inspect(p)['unreviewed']) == 3
    (Path(p.records[0]['source_root']) / p.records[0]['relative_path']).unlink()
    report = inspect(p)
    assert any('No such file' in x['issue'] for x in report['issues'])


def test_groups_do_not_leak_and_are_reproducible(tmp_path):
    records = [dict(image_id=f'{g}-{i}', group_id=g, relative_path=f'{g}/{i}.png')
               for g in ('a', 'b', 'c', 'd', 'e', 'f') for i in range(3)]
    assignment = split_groups(records, seed=7)
    assert assignment == split_groups(records, seed=7)
    assert all(len({assignment[f'{g}-{i}'] for i in range(3)}) == 1 for g in ('a', 'b', 'c', 'd', 'e', 'f'))


def test_gui_draw_save_and_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    p = project(tmp_path)
    window = MainWindow()
    window.resize(1200, 750)
    window.show()
    window.set_project(p)
    app.processEvents()
    rid = p.records[0]['image_id']
    assert window.current_id == rid
    view = window.view
    start = view.mapFromScene(QPointF(2, 2))
    end = view.mapFromScene(QPointF(25, 12))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()
    assert len(Project(p.output).annotation(rid)['objects']) == 1
    assert Project(p.output).annotation(rid)['status'] == 'positive'
    window.close()


def test_gui_negative_and_skip_remains_unreviewed(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    p = project(tmp_path)
    window = MainWindow(); window.show(); window.set_project(p); app.processEvents()
    first, second, third = [r['image_id'] for r in p.records]
    window.mark_negative()
    assert Project(p.output).annotation(first)['status'] == 'negative'
    window.save_next()
    assert window.current_id == second
    window.save_next()
    assert window.current_id == third
    assert Project(p.output).annotation(second)['status'] == 'unreviewed'
    window.next_unreviewed()
    assert window.current_id == second
    window.close()
