import uuid
import json
from pathlib import Path

from app.services.image_scanner import scan
from app.utils.core import SCHEMA, atomic_json, class_hash, now, read_json, separate_paths


class Project:
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.file = self.output / 'project.json'
        recovery_notes = []
        try:
            json.loads(self.file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            recovery_notes.append('project.json 损坏或缺失，尝试从临时文件/备份恢复')
        self.data = read_json(self.file)
        if self.data.get('schema_version') != SCHEMA or self.data.get('class_config_hash') != class_hash():
            raise ValueError('项目版本或类别配置不匹配，拒绝静默改变类别')
        self.records = self.data['images']
        self.by_id = {r['image_id']: r for r in self.records}
        self.load_errors = recovery_notes
        for r in self.records:
            path = self.annotation_path(r['image_id'])
            if path.exists():
                try:
                    try:
                        json.loads(path.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        self.load_errors.append(f"{r['relative_path']}: 标注 JSON 损坏，已尝试恢复")
                    r['status'] = read_json(path)['status']
                except Exception as error:
                    self.load_errors.append(f"{r['relative_path']}: {error}")

    @classmethod
    def create(cls, source, output, worker_id='worker_A', progress=None, source_id=None):
        separate_paths(source, output)
        output = Path(output).resolve()
        if output.exists() and any(output.iterdir()):
            raise ValueError('输出目录已有内容；请打开已有项目或选择空目录')
        source_id = source_id or str(uuid.uuid4())
        images, errors = scan(source, source_id, progress)
        if not images:
            raise ValueError('未找到可解码图片；' + '; '.join(errors[:5]))
        atomic_json(output / 'project.json', dict(schema_version=SCHEMA, project_id=str(uuid.uuid4()),
                    project_type='worker', worker_id=worker_id, class_config_hash=class_hash(),
                    source_id=source_id, source_root=str(Path(source).resolve()), images=images,
                    scan_errors=errors, created_at=now()))
        return cls(output)

    def rescan(self, progress=None):
        source = self.data['source_root']
        images, errors = scan(source, self.data['source_id'], progress)
        old = self.by_id
        for r in images:
            if r['image_id'] in old:
                r['status'] = old[r['image_id']]['status']
                if r['image_sha256'] != old[r['image_id']]['image_sha256']:
                    errors.append(f"来源文件内容变化: {r['relative_path']}")
                    r.update({k: old[r['image_id']][k] for k in ('image_sha256', 'image_width', 'image_height')})
        missing = [r for r in self.records if r['image_id'] not in {x['image_id'] for x in images}]
        self.data['images'] = images + missing
        self.data['scan_errors'] = errors
        self.records = self.data['images']
        self.by_id = {r['image_id']: r for r in self.records}
        self.save_index()
        return errors

    def save_index(self):
        atomic_json(self.file, self.data)

    def annotation_path(self, image_id):
        return self.output / 'annotations' / f'{image_id}.json'

    def annotation(self, image_id):
        r = self.by_id[image_id]
        path = self.annotation_path(image_id)
        if path.exists():
            ann = read_json(path)
            if ann.get('class_config_hash') != self.data['class_config_hash']:
                raise ValueError(f'标注类别配置不匹配: {path}')
            return ann
        return dict(schema_version=SCHEMA, image_id=image_id, relative_path=r['relative_path'],
                    status=r['status'], objects=[], updated_at=None,
                    annotator_id=self.data['worker_id'], class_config_hash=self.data['class_config_hash'])

    def save_annotation(self, image_id, objects, status):
        from app.services.validation_service import validate_annotation
        r = self.by_id[image_id]
        if self.data['project_type'] == 'master':
            for obj in objects:
                obj.setdefault('provenance', [dict(worker_id='master', package_id=None,
                                                    original_object_id=None, manually_corrected=True)])
        ann = dict(schema_version=SCHEMA, image_id=image_id, relative_path=r['relative_path'],
                   status=status, objects=objects, updated_at=now(),
                   annotator_id=self.data['worker_id'], class_config_hash=self.data['class_config_hash'])
        if self.data['project_type'] == 'master' and self.annotation_path(image_id).exists():
            old = self.annotation(image_id)
            ann['provenance'] = old.get('provenance', [])
        errors = validate_annotation(r, ann)
        if errors:
            raise ValueError('; '.join(errors))
        atomic_json(self.annotation_path(image_id), ann)
        r['status'] = status
        self.save_index()

    def image_path(self, record):
        from app.utils.core import safe_path
        if self.data['project_type'] == 'master':
            return safe_path(self.output, record['package_image_path'])
        return safe_path(record['source_root'], record['relative_path'])
