# 智能割草机视觉数据标注工具

Windows 独立 EXE：[标注人员使用说明](docs/EXE_USER_GUIDE.md)；[打包验收记录](docs/EXE_VALIDATION.md)。正式程序位于 `dist/MowerAnnotator.exe`，可直接双击运行。

Windows 11 / Python 3.11 / PySide6 桌面工具。原图只读；标注、便携包、Master 和 YOLO 数据集分别保存在用户选择的输出目录。无需训练框架、ROS 或 CUDA。

## 安装与运行

在 **Conda PowerShell Prompt** 中进入本目录，运行：

```powershell
.\setup.ps1
.\run.ps1
```

`setup.ps1` 先检查 `mower-annotator` 是否存在；仅在不存在时创建 Python 3.11 环境，然后安装 `requirements.txt`。测试：`.\test.ps1`。若当前电脑暂时无法调用 Conda，也可在已有具备依赖的 Python 环境中执行 `python main.py`、`python -m pytest -q --basetemp=.pytest_tmp`。

## 主要流程

1. 选择图片输入目录和空的标注输出目录，点击“新建项目”，输入标注人员 ID 与数据来源 ID。多人标同一批图时使用相同的数据来源 ID。可用“打开已有标注项目”恢复 `project.json` 所在目录。
2. 左侧选择图片与状态筛选；中间绘制或编辑框；右侧选类别、改类别、设状态。框与状态自动保存，切换或关闭时再次保存。
3. “标注检查”查看未标注、无效框、丢失文件、重复图片和类别计数。“重新扫描”在后台扫描新增图片，保持已有标注。
4. 每人点击“生成便携标注包”，在所选父目录产生新的 `worker_package_vN`。
5. 合并窗口添加多个包、先检查、逐一处理冲突，选择空目录生成 Master。成功后主窗口自动打开 Master。
6. “导出 YOLO”设置 train/val/test 比例和种子。仅导出 positive/negative，按 `group_id` 分组，输出新的 `dataset_v0.N`。

普通标注步骤见 [用户指南](docs/USER_GUIDE.md)，格式见 [数据格式](docs/data_format.md)，合并规则见 [合并规则](docs/merge_rules.md)。

### 数据安全

新项目的输出目录必须为空，且不能与输入目录互相包含。每图标注是独立 JSON，原子替换并保留 `.bak`。便携包和数据集每次创建新版本目录。项目与包均保存类别配置哈希；打开或合并时不匹配会被拒绝。请勿手动修改 `classes.yaml` 中固定类别。

### 当前约束

自动推断 `group_id` 从相对路径中识别 `sample_...`、`Snapshot...`、`session_...` 等会话目录，使用完整目录前缀避免不同父目录同名。无法可靠识别的图片没有组号，导出前须用右侧按钮依据采集会话逐张设置 `group_id`。导出至少需要三个独立组。大型图片按需加载，切换时释放上一张场景；全量校验和打包会占用与数据量相应的时间与磁盘空间。
