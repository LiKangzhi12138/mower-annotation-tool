from collections import Counter, defaultdict

from app.services.image_scanner import image_size
from app.utils.core import NAMES, STATUSES, bbox_valid, sha256


def annotation_signature(ann):
    return (ann['status'], tuple(sorted((x['class_id'], tuple(round(float(v), 6) for v in x['bbox']))
                                         for x in ann['objects'])))


def validate_annotation(record, ann):
    errors = []
    if ann.get('image_id') != record['image_id']:
        errors.append('image_id 不匹配')
    status, objects = ann.get('status'), ann.get('objects', [])
    if status not in STATUSES or not isinstance(objects, list):
        return ['状态或对象列表非法']
    if status == 'positive' and not objects:
        errors.append('positive 没有目标框')
    if status in ('negative', 'unreviewed', 'exclude') and objects:
        errors.append(f'{status} 不能包含目标框')
    ids = set()
    for obj in objects:
        oid = obj.get('object_id')
        if not oid or oid in ids:
            errors.append('object_id 缺失或重复')
        ids.add(oid)
        cid = obj.get('class_id')
        if type(cid) is not int or cid not in range(4) or obj.get('class_name') != NAMES[cid]:
            errors.append('类别 ID 或名称非法')
        if not bbox_valid(obj.get('bbox'), record['image_width'], record['image_height']):
            errors.append('框越界或尺寸非法')
    return errors


def inspect(project, verify_hash=False):
    issues, stats = [], Counter()
    hashes = defaultdict(list)
    for r in project.records:
        rid = r['image_id']
        try:
            ann = project.annotation(rid)
            stats[ann['status']] += 1
            for obj in ann['objects']:
                stats[f"class_{obj.get('class_id')}"] += 1
            for error in validate_annotation(r, ann):
                issues.append(dict(image_id=rid, path=r['relative_path'], issue=error))
            path = project.image_path(r)
            image_size(path)
            if verify_hash and sha256(path) != r['image_sha256']:
                issues.append(dict(image_id=rid, path=r['relative_path'], issue='原图 SHA256 不匹配'))
        except Exception as error:
            issues.append(dict(image_id=rid, path=r['relative_path'], issue=str(error)))
        hashes[r['image_sha256']].append(rid)
    for ids in hashes.values():
        if len(ids) > 1:
            for rid in ids:
                issues.append(dict(image_id=rid, path=project.by_id[rid]['relative_path'], issue='可能重复内容'))
    stats['total'] = len(project.records)
    stats['completed'] = stats['positive'] + stats['negative']
    return dict(stats=dict(stats), issues=issues,
                unreviewed=[r for r in project.records if r['status'] == 'unreviewed'])
