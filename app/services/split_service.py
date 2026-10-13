import random
from collections import defaultdict


def split_groups(records, ratios=(0.7, 0.2, 0.1), seed=42):
    if len(ratios) != 3 or any(x <= 0 for x in ratios) or abs(sum(ratios) - 1) > 1e-6:
        raise ValueError('训练/验证/测试比例必须为正且总和为 1')
    groups = defaultdict(list)
    for r in records:
        if not r.get('group_id'):
            raise ValueError(f"缺少 group_id，请先确定采集分组规则: {r['relative_path']}")
        groups[r['group_id']].append(r)
    if len(groups) < 3:
        raise ValueError('至少需要三个独立 group_id 才能划分 train/val/test')
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    targets = [len(records) * x for x in ratios]
    bins = [[], [], []]
    counts = [0, 0, 0]
    for i, group in enumerate(keys):
        if i < 3:
            bucket = i
        else:
            bucket = max(range(3), key=lambda j: (targets[j] - counts[j]) / targets[j])
        bins[bucket].extend(groups[group])
        counts[bucket] += len(groups[group])
    actual = [count / len(records) for count in counts]
    if max(abs(a - target) for a, target in zip(actual, ratios)) > 0.15:
        raise ValueError('现有 group_id 无法接近所选比例：实际 train/val/test 为 '
                         + '/'.join(f'{value:.1%}' for value in actual)
                         + '；请调整比例或采集分组（容差 15 个百分点）')
    return {r['image_id']: name for name, bucket in zip(('train', 'val', 'test'), bins) for r in bucket}
