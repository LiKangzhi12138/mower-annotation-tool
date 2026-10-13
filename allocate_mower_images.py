#!/usr/bin/env python3
"""Allocate one image per sample folder into worker_XX/images directly (no nested sample folders).

Python >=3.11 and Pillow required. Does not alter the source tree.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:
    raise SystemExit("缺少 Pillow：请在 mower-annotator 环境中运行，或执行 python -m pip install Pillow")

SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
DEFAULT_SOURCE = r"E:\workspace\mower-data\samples\airport_mower_samples"
DEFAULT_OUTPUT = r"E:\workspace\mower-annotation-distribution"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_image(path: Path) -> dict[str, Any]:
    # decode the whole image; verify() alone might not detect truncated pixels
    with Image.open(path) as image:
        width, height = image.size
        orientation = image.getexif().get(274, 1)
        image.load()
        if width <= 0 or height <= 0:
            raise ValueError("图像宽高非法")
    return {"width": width, "height": height, "exif_orientation": orientation}


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def safe_flat_filename(item: dict[str, Any], used: set[str]) -> str:
    """Create a readable, deterministic Windows filename without worker collisions.

    E.g. sample_000001__image_00.png. Fall back to a short source-path hash
    for exceptional name collisions or overlong names.
    """
    original = Path(item["filename"])
    proposed = f'{item["sample_id"]}__{original.name}'
    if len(proposed) > 180 or proposed.casefold() in used:
        suffix = hashlib.sha256(item["source_relative_path"].encode("utf-8")).hexdigest()[:12]
        ext = original.suffix
        stem = f'{item["sample_id"]}__{original.stem}'
        limit = max(1, 180 - len(ext) - len(suffix) - 2)
        proposed = f'{stem[:limit]}__{suffix}{ext}'
    key = proposed.casefold()
    if key in used:
        raise ValueError(f"扁平文件名冲突，无法安全分配：{item['source_relative_path']}")
    used.add(key)
    return proposed


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="110组割草机数据：每组取一张并均衡分给标注人员")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="原始样本目录")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT, help="独立分配输出根目录")
    parser.add_argument("--workers", type=int, help="标注人数；不填会交互式询问")
    parser.add_argument("--seed", type=int, default=20261013, help="固定随机种子，默认20261013")
    parser.add_argument("--expected-groups", type=int, default=110, help="预期样本文件夹数，默认110")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    source = Path(args.source).expanduser().resolve()
    root = Path(args.output_root).expanduser().resolve()
    workers = args.workers
    if workers is None:
        try:
            workers = int(input("请输入实际标注人数（例如3）：").strip())
        except (ValueError, EOFError):
            print("标注人数无效，请使用 --workers 指定正整数。", file=sys.stderr)
            return 2
    if workers < 1:
        print("标注人数必须至少为1。", file=sys.stderr)
        return 2
    if not source.is_dir():
        print(f"原始数据目录不存在：{source}", file=sys.stderr)
        return 2
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        print("分配结果目录不得与原始数据目录相同，或互相包含。", file=sys.stderr)
        return 2

    folders = [x for x in source.iterdir() if x.is_dir()]
    if len(folders) != args.expected_groups:
        print(f"检查未通过：找到 {len(folders)} 个一级样本文件夹，预期 {args.expected_groups} 个。没有复制任何数据。", file=sys.stderr)
        print("请确认目录和实际文件夹数量；若数量确实变化，可显式修改 --expected-groups。", file=sys.stderr)
        return 3
    if workers > len(folders):
        print("标注人数不能大于样本文件夹数量。", file=sys.stderr)
        return 2

    print(f"检查原始数据：{source}")
    selections = []
    problems = []
    failures = []
    for folder in sorted(folders, key=lambda p: (p.name.casefold(), p.name)):
        image_dir = folder / "images"
        if not image_dir.is_dir():
            problems.append(f"{folder.name}：缺失 images 子目录")
            continue
        candidates = sorted(
            (p for p in image_dir.iterdir() if p.is_file() and p.suffix.casefold() in SUPPORTED),
            key=lambda p: (p.name.casefold(), p.name),
        )
        if not candidates:
            problems.append(f"{folder.name}：images 下没有可识别图片")
            continue
        selection = None
        for candidate in candidates:
            try:
                info = valid_image(candidate)
                selection = {"sample_id": folder.name,
                             "source_relative_path": candidate.relative_to(source).as_posix(),
                             "candidate_count": len(candidates),
                             "source_path": candidate,
                             "filename": candidate.name,
                             **info,
                             "sha256": sha256_file(candidate)}
                break
            except (OSError, ValueError, SyntaxError) as exc:
                failures.append({"sample_id": folder.name, "filename": candidate.name, "error": str(exc)})
        if selection is None:
            problems.append(f"{folder.name}：所有 {len(candidates)} 张候选图片都无法解码")
        else:
            selections.append(selection)

    if problems:
        print("\n检查未通过，停止分配；不生成不完整的任务包：", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        print(f"有效样本数 {len(selections)} / {len(folders)}，没有复制任何数据。", file=sys.stderr)
        return 3

    # Shuffle at the sample-folder level, then round-robin for sizes differing by at most one.
    rng = random.Random(args.seed)
    ordered = sorted(selections, key=lambda x: (x["sample_id"].casefold(), x["sample_id"]))
    rng.shuffle(ordered)
    used_filenames: dict[str, set[str]] = defaultdict(set)
    for index, item in enumerate(ordered):
        worker_id = f"worker_{index % workers + 1:02d}"
        item["worker_id"] = worker_id
        # All selected images go directly into worker_XX/images; no sample folders.
        item["assigned_filename"] = safe_flat_filename(item, used_filenames[worker_id])
        item["assignment_relative_path"] = f'{worker_id}/images/{item["assigned_filename"]}'
        item["group_id_candidate"] = item["sample_id"]

    duplicate_hashes = defaultdict(list)
    for item in ordered:
        duplicate_hashes[item["sha256"]].append(item["sample_id"])
    duplicate_rows = [
        {"sha256": content_hash, "sample_ids": ";".join(samples), "count": len(samples)}
        for content_hash, samples in sorted(duplicate_hashes.items()) if len(samples) > 1
    ]

    batch_name = f'batch_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:6]}'
    root.mkdir(parents=True, exist_ok=True)
    temp = root / (".staging_" + batch_name)
    batch = root / batch_name
    temp.mkdir(exist_ok=False)
    try:
        (temp / "reports").mkdir()
        (temp / "annotation_outputs").mkdir()
        for i in range(workers):
            worker_id = f"worker_{i + 1:02d}"
            (temp / worker_id / "images").mkdir(parents=True)
            (temp / "annotation_outputs" / worker_id).mkdir(parents=True)
            worker_note = (
                f"标注任务：{worker_id}\n"
                "1. 打开智能割草机标注工具 EXE。\n"
                "2. 图片输入路径选择当前 worker 文件夹里的 images 子目录（里面直接都是图片）。\n"
                "3. 标注输出路径选择同一批次 annotation_outputs 下对应的 worker 文件夹。\n"
                "4. 按统一的四类标签进行标注，检查未标注列表。\n"
                "5. 完成后通过软件导出完整 Worker Package，交给管理员。\n"
                "图片直接位于当前 worker/images 目录下，图片名包含来源 sample 文件夹名。\n"
                "task_manifest.csv 记录图片与原始样本的映射，请随任务一起保留。\n"
                "不要直接把 annotation_output 当作 Worker Package 合并，除非软件明确支持。\n"
            )
            (temp / worker_id / "使用说明.txt").write_text(worker_note, encoding="utf-8-sig")

        for index, item in enumerate(ordered, 1):
            destination = temp / item["assignment_relative_path"]
            shutil.copy2(item["source_path"], destination)
            if sha256_file(destination) != item["sha256"]:
                raise IOError(f"复制后 SHA256 不匹配：{destination}")
            if index % 20 == 0 or index == len(ordered):
                print(f"已复制和校验 {index}/{len(ordered)} 张")

        cols = ["sample_id", "source_relative_path", "filename", "candidate_count", "width", "height", "exif_orientation", "sha256"]
        assigned_cols = cols + ["worker_id", "assigned_filename", "assignment_relative_path", "group_id_candidate"]
        write_csv(temp / "reports" / "selection_manifest.csv", ordered, cols)
        write_csv(temp / "reports" / "allocation_manifest.csv", ordered, assigned_cols)
        # Every worker gets their own provenance manifest, even if given only their folder.
        for i in range(workers):
            worker_id = f"worker_{i + 1:02d}"
            worker_rows = [item for item in ordered if item["worker_id"] == worker_id]
            write_csv(temp / worker_id / "task_manifest.csv", worker_rows, assigned_cols)
        write_csv(temp / "reports" / "invalid_candidates.csv", failures, ["sample_id", "filename", "error"])
        write_csv(temp / "reports" / "exact_duplicate_images.csv", duplicate_rows, ["sha256", "sample_ids", "count"])
        counts = dict(sorted(Counter(item["worker_id"] for item in ordered).items()))
        stats = {"source": str(source), "batch": batch_name, "seed": args.seed,
                 "expected_groups": args.expected_groups, "found_groups": len(folders),
                 "chosen_images": len(ordered), "worker_count": workers, "per_worker": counts,
                 "output_layout": "worker_XX/images/<sample_name>__<filename>",
                 "duplicate_sha256_groups": len(duplicate_rows),
                 "invalid_candidates_skipped": len(failures),
                 "note": "每个一级样本文件夹选一张；group_id暂以样本文件夹名保留，训练集分组需额外核对采集会话。"}
        (temp / "reports" / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = [f"原始数据：{source}", f"源样本目录数：{len(folders)}", f"选中的图片数：{len(ordered)}",
                   f"分配人数：{workers}", f"随机种子：{args.seed}", "每人图片数："]
        summary.extend(f"  {who}: {count}" for who, count in counts.items())
        summary.extend([f"完全重复内容组数：{len(duplicate_rows)}",
                        f"排序靠前但解码失败、已跳过的候选数：{len(failures)}",
                        "规则：一级样本文件夹为单位，按文件名排序取首张可完整解码的图片。",
                   "输出：图片直接放在 worker_XX/images 下（无 sample 子目录）。",
                   "标注输出：同批次 annotation_outputs/worker_XX，与图片输入目录分离。",
                   "命名：sample文件夹名__原图片名；保留原始文件名、路径与哈希映射。",
                        "说明：分配给标注员的任务 ≠ 最终 Train/Val/Test 划分；不得以此作为防数据泄漏保证。"])
        (temp / "reports" / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
        temp.rename(batch)
    except Exception:
        print(f"复制或校验发生异常，尚未发布完整任务包。检查临时目录：{temp}", file=sys.stderr)
        raise

    print("\n分配完成：" + str(batch))
    print("\n".join(summary))
    print("报告目录：" + str(batch / "reports"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
