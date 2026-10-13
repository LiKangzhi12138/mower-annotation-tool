import hashlib
import json
import os
import shutil
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA = 1
NAMES = ('stone', 'tree', 'person', 'other_roadblock')
STATUSES = ('unreviewed', 'positive', 'negative', 'uncertain', 'exclude')
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
CLASS_FILE = RESOURCE_ROOT / 'config' / 'classes.yaml'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def classes(path=CLASS_FILE):
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if [(x['id'], x['name']) for x in data['classes']] != list(enumerate(NAMES)):
        raise ValueError('类别配置必须严格为固定的四类及 ID')
    return data


def class_hash(path=CLASS_FILE):
    return hashlib.sha256(json.dumps(classes(path), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + '.bak'))
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path, recover=True):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        if not recover:
            raise ValueError(f'JSON 无法读取: {path}: {error}') from error
        for candidate in sorted(path.parent.glob(path.name + '.*.tmp'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                recovered = json.loads(candidate.read_text(encoding='utf-8'))
                os.replace(candidate, path)
                return recovered
            except (OSError, ValueError):
                continue
        backup = path.with_suffix(path.suffix + '.bak')
        if backup.exists():
            try:
                return json.loads(backup.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        raise ValueError(f'JSON 无法读取: {path}: {error}') from error


def bbox_valid(box, width, height):
    try:
        x1, y1, x2, y2 = (float(v) for v in box)
        return 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
    except (ValueError, TypeError):
        return False


def yolo_box(box, width, height):
    if not bbox_valid(box, width, height):
        raise ValueError('非法 bbox')
    x1, y1, x2, y2 = box
    return ((x1 + x2) / (2 * width), (y1 + y2) / (2 * height),
            (x2 - x1) / width, (y2 - y1) / height)


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'不安全路径: {relative}')
    return path


def separate_paths(source, output):
    a, b = Path(source).resolve(), Path(output).resolve()
    if a == b or a in b.parents or b in a.parents:
        raise ValueError('输入和输出目录不能相同或互相包含')
