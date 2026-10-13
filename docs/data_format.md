# 数据格式规范 v1

所有 JSON 为 UTF-8，`schema_version=1`。`config/classes.yaml` 固定四类，`class_config_hash` 是 YAML 解析后的对象按 JSON 字段排序、UTF-8、SHA256 计算的十六进制值；各端必须一致。

## 单人项目

`project.json` 包含 `project_id`、`project_type`、`worker_id`、`source_id`、`source_root`、`class_config_hash`、`images`。每个索引行含 `image_id`、`source_id`、`relative_path`、`original_filename`、`image_width`、`image_height`、`image_sha256`、`group_id`、`status`、`source_root`，以及可用时的 `capture_time`、`camera_model`。`source_root` 仅为本机路径绑定。`image_id` 是 `UUID5(URL 命名空间, source_id + '/' + POSIX 相对路径)`，不依赖文件名唯一性；跨电脑相同图片由 SHA256 辅助识别。

`annotations/<image_id>.json` 包含 `schema_version`、`image_id`、`relative_path`、`status`、`objects`、`updated_at`、`annotator_id`、`class_config_hash`。对象含 `object_id`、`class_id`、`class_name`、`bbox`。`bbox=[x1,y1,x2,y2]` 是 EXIF 方向应用后的原始像素坐标，满足 `0≤x1<x2≤width`、`0≤y1<y2≤height`。读取、展示和导出统一应用 EXIF 旋转，源文件不改动。

状态：`unreviewed` 未审核，`positive` 至少一个有效框，`negative` 人工确认零框，`uncertain` 存疑，`exclude` 排除。只有 positive 与 negative 可进入训练。

## Worker Package

`package.json` 含版本、`package_id`、`worker_id`、类别哈希、创建时间、图片与标注数量、来源 ID。`classes.yaml` 为类别快照。`manifests/images.csv` 每图一行，含索引字段及 `package_image_path`。图片置于 `images/<image_id>.<ext>`，标注置于 `annotations/<image_id>.json`。CSV 的相对路径只在包内解析，不能越过包根。验证数量、尺寸与 SHA256。包可移动到其他电脑，无需原机绝对路径。

## Master 与 YOLO

Master 有 `master.json`、`project.json`、类别快照、manifest、原图副本、每图标注及 `merge_reports/conflicts.json`。标注顶层 `provenance` 逐项保存 Worker ID、Package ID 和原 image_id；每个框的 `provenance` 还保存来源 Worker、Package 和原 object_id。Master 中新建或手动修正的框标记 `manually_corrected`。

YOLO 目录 `dataset_v0.N` 有 `images/{train,val,test}`、`labels/{train,val,test}`、`data.yaml`、`manifest.csv`、`split_manifest.csv`、`dataset_info.json`。输出图片经过 EXIF 方向校正并转为 PNG。每个框归一化为 `class_id x_center y_center width height`，精度 8 位小数。negative 对应空 TXT。数据集记录随机种子、比例和 `group-greedy-v1` 算法版本。组划分后若任一子集实际比例与目标相差超过 15 个百分点，导出会报错，提示调整比例或分组。
