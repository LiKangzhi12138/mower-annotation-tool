import csv
import shutil
import uuid
from pathlib import Path

from app.services.image_scanner import image_size
from app.services.validation_service import validate_annotation, annotation_signature
from app.utils.core import CLASS_FILE, SCHEMA, atomic_json, class_hash, now, read_json, sha256, separate_paths

FIELDS = ('image_id', 'source_id', 'relative_path', 'original_filename', 'image_width',
          'image_height', 'image_sha256', 'group_id', 'status', 'capture_time', 'camera_model',
          'package_image_path')


def _write_manifest(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, '') for k in FIELDS})


def _read_manifest(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def make_package(project, destination):
    destination = Path(destination).resolve()
    if project.data['project_type'] == 'worker':
        separate_paths(project.data['source_root'], destination)
    destination.mkdir(parents=True, exist_ok=True)
    version = 1
    while (destination / f'worker_package_v{version}').exists():
        version += 1
    final = destination / f'worker_package_v{version}'
    temp = destination / f'.worker_package_v{version}_{uuid.uuid4().hex}.tmp'
    try:
        temp.mkdir()
        records = []
        for r in project.records:
            source = project.image_path(r)
            if sha256(source) != r['image_sha256']:
                raise ValueError(f"原图缺失或 SHA256 变化: {r['relative_path']}")
            rel = f"images/{r['image_id']}{source.suffix.lower()}"
            target = temp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if sha256(target) != r['image_sha256']:
                raise ValueError(f'复制校验失败: {source}')
            ann = project.annotation(r['image_id'])
            errors = validate_annotation(r, ann)
            if errors:
                raise ValueError(f"{r['relative_path']}: {'; '.join(errors)}")
            atomic_json(temp / 'annotations' / f"{r['image_id']}.json", ann)
            records.append(dict(r, package_image_path=rel))
        _write_manifest(temp / 'manifests' / 'images.csv', records)
        shutil.copy2(CLASS_FILE, temp / 'classes.yaml')
        atomic_json(temp / 'package.json', dict(schema_version=SCHEMA, package_id=str(uuid.uuid4()),
                    worker_id=project.data['worker_id'], class_config_hash=class_hash(), created_at=now(),
                    image_count=len(records), annotation_count=len(records),
                    source_identifiers=sorted({r['source_id'] for r in records})))
        validate_package(temp)
        temp.rename(final)
        return final
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def validate_package(root):
    root = Path(root)
    meta = read_json(root / 'package.json', recover=False)
    if meta.get('schema_version') != SCHEMA:
        raise ValueError('不支持的包版本')
    if meta.get('class_config_hash') != class_hash(root / 'classes.yaml') or meta['class_config_hash'] != class_hash():
        raise ValueError('类别配置或哈希不一致')
    records = _read_manifest(root / 'manifests' / 'images.csv')
    if len(records) != int(meta['image_count']) or len(records) != int(meta['annotation_count']):
        raise ValueError('包内图片或标注数量不匹配')
    seen, annotations, signatures = set(), {}, {}
    for r in records:
        rid = r['image_id']
        if rid in seen:
            raise ValueError(f'包内重复 image_id: {rid}')
        seen.add(rid)
        r['image_width'], r['image_height'] = int(r['image_width']), int(r['image_height'])
        r['group_id'] = r['group_id'] or None
        from app.utils.core import safe_path
        image = safe_path(root, r['package_image_path'])
        if sha256(image) != r['image_sha256'] or image_size(image) != (r['image_width'], r['image_height']):
            raise ValueError(f'图片缺失、尺寸或 SHA256 不匹配: {image}')
        ann = read_json(root / 'annotations' / f'{rid}.json', recover=False)
        if ann.get('relative_path') != r['relative_path'] or ann.get('status') != r['status']:
            raise ValueError(f'标注与索引不匹配: {rid}')
        if ann.get('class_config_hash') != meta['class_config_hash']:
            raise ValueError(f'标注类别哈希不匹配: {rid}')
        errors = validate_annotation(r, ann)
        if errors:
            raise ValueError(f"{rid}: {'; '.join(errors)}")
        annotations[rid] = ann
        signature = annotation_signature(ann)
        if r['image_sha256'] in signatures and signatures[r['image_sha256']] != signature:
            raise ValueError(f'包内相同内容存在冲突标注: {rid}')
        signatures[r['image_sha256']] = signature
    if len(list((root / 'annotations').glob('*.json'))) != len(records):
        raise ValueError('标注文件数量与 manifest 不一致')
    if len([p for p in (root / 'images').rglob('*') if p.is_file()]) != len(records):
        raise ValueError('图片文件数量与 manifest 不一致')
    return meta, records, annotations
