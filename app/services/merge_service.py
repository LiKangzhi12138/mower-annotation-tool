import csv
import json
import shutil
import uuid
from collections import defaultdict
from pathlib import Path

from app.services.worker_package import validate_package
from app.services.validation_service import annotation_signature
from app.utils.core import CLASS_FILE, SCHEMA, atomic_json, now, sha256


def plan_merge(package_paths):
    if len(package_paths) < 2:
        raise ValueError('至少需要两个标注包')
    packages, by_hash, source_paths = [], defaultdict(list), defaultdict(set)
    package_ids = set()
    for path in package_paths:
        root = Path(path).resolve()
        meta, records, annotations = validate_package(root)
        if meta['package_id'] in package_ids:
            raise ValueError('同一标注包被重复加入')
        package_ids.add(meta['package_id'])
        packages.append(dict(root=root, meta=meta, records=records, annotations=annotations))
        for r in records:
            item = dict(root=root, package=meta, record=r, annotation=annotations[r['image_id']])
            by_hash[r['image_sha256']].append(item)
            source_paths[(r['source_id'], r['relative_path'])].add(r['image_sha256'])
    conflicts = []
    for key, hashes in source_paths.items():
        if len(hashes) > 1:
            conflicts.append(dict(key='source:' + '|'.join(key), type='同一来源路径内容不同',
                                  image_id='', workers=[], files=[key[1]], difference=list(hashes)))
    for digest, items in by_hash.items():
        signatures = {annotation_signature(x['annotation']) for x in items}
        if len(signatures) > 1:
            conflicts.append(dict(key=digest, type='相同图片标注不同', image_id=items[0]['record']['image_id'],
                                  workers=[x['package']['worker_id'] for x in items],
                                  files=[str(x['root'] / x['record']['package_image_path']) for x in items],
                                  difference=[dict(package_id=x['package']['package_id'], worker_id=x['package']['worker_id'],
                                                   annotation=x['annotation']) for x in items]))
    return dict(packages=packages, by_hash=by_hash, conflicts=conflicts)


def merge(plan, destination, resolutions=None):
    resolutions = resolutions or {}
    unresolved = [c for c in plan['conflicts'] if c['key'] not in resolutions]
    if unresolved:
        raise ValueError(f'还有 {len(unresolved)} 个未解决冲突，不能发布 Master')
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Master 输出目录已有内容，请选择空目录以保护已有版本')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.parent / f'.master_{uuid.uuid4().hex}.tmp'
    try:
        if any(destination == x['root'] or destination in x['root'].parents or x['root'] in destination.parents
               for x in plan['packages']):
            raise ValueError('Master 输出目录不能与输入包互相包含')
        temp.mkdir()
        records, provenance, used_ids = [], {}, set()
        excluded = set()
        manual_by_hash = {}
        for conflict in plan['conflicts']:
            if conflict['type'] == '同一来源路径内容不同':
                selected = resolutions[conflict['key']]
                selected_id = selected['package_id'] if isinstance(selected, dict) else selected
                source_id, relative = conflict['key'][7:].split('|', 1)
                matches = [x for group in plan['by_hash'].values() for x in group
                           if x['record']['source_id'] == source_id and x['record']['relative_path'] == relative]
                if selected_id not in {x['package']['package_id'] for x in matches}:
                    raise ValueError('来源路径冲突选择无效')
                if isinstance(selected, dict):
                    chosen_source = next(x for x in matches if x['package']['package_id'] == selected_id)
                    manual_by_hash[chosen_source['record']['image_sha256']] = selected
                excluded.update((x['package']['package_id'], x['record']['image_id']) for x in matches
                                if x['package']['package_id'] != selected_id)
        for digest, all_items in plan['by_hash'].items():
            items = [x for x in all_items if (x['package']['package_id'], x['record']['image_id']) not in excluded]
            if not items:
                continue
            chosen_id = resolutions.get(digest)
            manual = chosen_id if isinstance(chosen_id, dict) else manual_by_hash.get(digest)
            if manual:
                chosen_id = manual['package_id']
            if chosen_id:
                candidates = [x for x in items if x['package']['package_id'] == chosen_id]
                if not candidates:
                    raise ValueError(f'无效冲突选择: {digest}')
                chosen = candidates[0]
            else:
                chosen = items[0]
            r = dict(chosen['record'])
            rid = r['image_id']
            if rid in used_ids:
                rid = str(uuid.uuid5(uuid.NAMESPACE_URL, digest))
                r['image_id'] = rid
            used_ids.add(rid)
            source = chosen['root'] / r['package_image_path']
            r['package_image_path'] = f'images/{rid}{source.suffix.lower()}'
            r['source_root'] = ''
            r['status'] = chosen['annotation']['status']
            target = temp / r['package_image_path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if sha256(target) != digest:
                raise ValueError('Master 图片复制校验失败')
            ann = dict(manual['annotation'] if manual else chosen['annotation'], image_id=rid,
                       relative_path=r['relative_path'])
            annotated_objects = []
            for obj in ann['objects']:
                matching = []
                for source_item in items:
                    for source_obj in source_item['annotation']['objects']:
                        if (source_obj['class_id'] == obj['class_id'] and
                                tuple(source_obj['bbox']) == tuple(obj['bbox'])):
                            matching.append(dict(worker_id=source_item['package']['worker_id'],
                                                 package_id=source_item['package']['package_id'],
                                                 original_object_id=source_obj['object_id']))
                if not matching:
                    matching = [dict(worker_id='master', package_id=None, original_object_id=None,
                                     manually_corrected=True)]
                annotated_objects.append(dict(obj, provenance=matching))
            ann['objects'] = annotated_objects
            if manual:
                from app.services.validation_service import validate_annotation
                errors = validate_annotation(r, ann)
                if errors:
                    raise ValueError(f"手动修正标注非法: {errors}")
            ann['provenance'] = [dict(worker_id=x['package']['worker_id'], package_id=x['package']['package_id'],
                                      original_image_id=x['record']['image_id']) for x in items]
            atomic_json(temp / 'annotations' / f'{rid}.json', ann)
            records.append(r)
            provenance[rid] = ann['provenance']
        shutil.copy2(CLASS_FILE, temp / 'classes.yaml')
        from app.utils.core import class_hash
        atomic_json(temp / 'master.json', dict(schema_version=SCHEMA, class_config_hash=class_hash(),
                    created_at=now(), package_ids=[x['meta']['package_id'] for x in plan['packages']],
                    image_count=len(records), provenance=provenance))
        atomic_json(temp / 'project.json', dict(schema_version=SCHEMA, project_id=str(uuid.uuid4()),
                    project_type='master', worker_id='master', class_config_hash=class_hash(),
                    source_id='master', source_root='', images=records, scan_errors=[], created_at=now()))
        (temp / 'manifests').mkdir()
        with (temp / 'manifests' / 'images.csv').open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0]) if records else [])
            writer.writeheader()
            writer.writerows(records)
        (temp / 'merge_reports').mkdir()
        atomic_json(temp / 'merge_reports' / 'conflicts.json', dict(conflicts=plan['conflicts'], resolutions=resolutions))
        from app.services.project_service import Project
        check = Project(temp)
        from app.services.validation_service import inspect
        issues = inspect(check, verify_hash=True)['issues']
        serious = [x for x in issues if x['issue'] != '可能重复内容']
        if serious:
            raise ValueError(f'Master 发布前验证失败: {serious[:3]}')
        removed_empty_destination = False
        if destination.exists():
            destination.rmdir()
            removed_empty_destination = True
        try:
            temp.rename(destination)
        except Exception:
            if removed_empty_destination:
                destination.mkdir(exist_ok=True)
            raise
        return destination
    finally:
        if temp.exists():
            shutil.rmtree(temp)
