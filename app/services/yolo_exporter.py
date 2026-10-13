import csv
import shutil
import uuid
from pathlib import Path

import yaml
from PIL import Image, ImageOps

from app.services.split_service import split_groups
from app.services.validation_service import inspect
from app.utils.core import NAMES, atomic_json, now, sha256, yolo_box, separate_paths


def export_yolo(project, destination, ratios=(0.7, 0.2, 0.1), seed=42):
    if project.data['project_type'] == 'worker':
        separate_paths(project.data['source_root'], destination)
    report = inspect(project, verify_hash=True)
    serious = [x for x in report['issues'] if x['issue'] != '可能重复内容']
    if serious:
        raise ValueError(f'导出前检查失败: {serious[:5]}')
    eligible = [r for r in project.records if r['status'] in ('positive', 'negative')]
    by_hash = {}
    for r in eligible:
        by_hash.setdefault(r['image_sha256'], r)
    records = list(by_hash.values())
    assignments = split_groups(records, ratios, seed)
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    version = 1
    while (destination / f'dataset_v0.{version}').exists():
        version += 1
    final = destination / f'dataset_v0.{version}'
    temp = destination / f'.dataset_v0.{version}_{uuid.uuid4().hex}.tmp'
    try:
        temp.mkdir()
        manifest = []
        for r in records:
            split = assignments[r['image_id']]
            source = project.image_path(r)
            with Image.open(source) as im:
                oriented = ImageOps.exif_transpose(im)
                image = temp / 'images' / split / f"{r['image_id']}.png"
                image.parent.mkdir(parents=True, exist_ok=True)
                oriented.convert('RGB').save(image)
            ann = project.annotation(r['image_id'])
            lines = []
            for obj in ann['objects']:
                coords = yolo_box(obj['bbox'], r['image_width'], r['image_height'])
                lines.append(str(obj['class_id']) + ' ' + ' '.join(f'{v:.8f}' for v in coords))
            label = temp / 'labels' / split / f"{r['image_id']}.txt"
            label.parent.mkdir(parents=True, exist_ok=True)
            label.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
            manifest.append(dict(image_id=r['image_id'], source_id=r['source_id'], relative_path=r['relative_path'],
                                 image_sha256=r['image_sha256'], group_id=r['group_id'], status=r['status'], split=split,
                                 image_path=image.relative_to(temp).as_posix(), label_path=label.relative_to(temp).as_posix()))
        data = dict(path=final.as_posix(), train='images/train', val='images/val', test='images/test',
                    nc=4, names=list(NAMES))
        (temp / 'data.yaml').write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
        for name in ('manifest.csv', 'split_manifest.csv'):
            with (temp / name).open('w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=list(manifest[0]) if manifest else [])
                writer.writeheader()
                writer.writerows(manifest)
        atomic_json(temp / 'dataset_info.json', dict(schema_version=1, created_at=now(), seed=seed,
                    ratios=dict(zip(('train', 'val', 'test'), ratios)), split_algorithm='group-greedy-v1',
                    image_count=len(records), source_project=str(project.output)))
        temp.rename(final)
        return final
    finally:
        if temp.exists():
            shutil.rmtree(temp)
