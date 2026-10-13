import uuid
import re
from pathlib import Path

from PIL import Image, ImageOps

from app.utils.core import sha256

EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}


def infer_group(relative):
    parts = Path(relative).parts[:-1]
    candidates = []
    for index, part in enumerate(parts):
        if re.match(r'(?i)^(snapshot|sample|session|video|recording|run|seq|group|bag)([-_ ]+.+|\d+)$', part):
            candidates.append('/'.join(parts[:index + 1]))
    return candidates[-1] if candidates else None


def image_size(path):
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        oriented = ImageOps.exif_transpose(im)
        return oriented.size


def image_metadata(path):
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            return {'capture_time': str(exif.get(36867) or exif.get(306) or ''),
                    'camera_model': str(exif.get(272) or '')}
    except Exception:
        return {'capture_time': '', 'camera_model': ''}


def scan(root, source_id, progress=None):
    root = Path(root).resolve()
    files = sorted((p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: str(p).lower())
    records, errors = [], []
    for i, path in enumerate(files):
        relative = path.relative_to(root).as_posix()
        try:
            width, height = image_size(path)
            metadata = image_metadata(path)
            group = infer_group(relative)
            records.append(dict(image_id=str(uuid.uuid5(uuid.NAMESPACE_URL, source_id + '/' + relative)),
                                source_id=source_id, relative_path=relative, original_filename=path.name,
                                image_width=width, image_height=height, image_sha256=sha256(path),
                                group_id=group, status='unreviewed', source_root=str(root), **metadata))
        except Exception as error:
            errors.append(f'{relative}: {error}')
        if progress:
            progress(i + 1, len(files))
    return records, errors
