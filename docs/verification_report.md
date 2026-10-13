# 终端验收报告

## 已实现

中文 PySide6 主界面；递归图片索引与 EXIF 一致坐标；矩形框绘制、选择、移动、缩放和类别修改；快捷键；五种审核状态；未标注与异常检查；独立 JSON 原子保存、备份和恢复；离线 Worker Package；多包校验、重复内容去重、冲突可视化与手动修正、Master 原子发布及逐框 provenance；按采集组划分并导出 YOLO train/val/test 数据集。

## 主要文件

`main.py`、`app/ui/*.py`、`app/services/*.py`、`app/utils/core.py`、`config/classes.yaml`、`tests/test_core.py`、`setup.ps1`、`run.ps1`、`test.ps1`、`README.md`、`docs/{USER_GUIDE,data_format,merge_rules,annotation_guidelines}.md`。

## 验证

命令：`$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q --basetemp=.pytest_tmp`

结果：**17 passed，0 failed**。另执行 `python -m compileall -q main.py app tests`、离屏 GUI 启动冒烟与三个真实 PNG 的只读解码。真实样本尺寸 2592×2048。PowerShell 三个脚本均通过语法解析。

## 运行和数据流

在可用的 Conda PowerShell Prompt 中依次执行 `.\setup.ps1` 和 `.\run.ps1`。首次选择输入目录、空输出目录，填写 Worker ID 与数据来源 ID。标完后点击“生成便携标注包”，选择包父目录，获取新版本 `worker_package_vN`。合并时点击“合并标注”，加入多个包，先检查并逐条处理冲突，选择空目录生成 Master。导出时点击“导出 YOLO”，设置比例与随机种子，选择输出父目录，获取 `dataset_v0.N`。

## 未验证与限制

当前机器的 `conda` 命令指向失效安装，返回 `The system cannot execute the specified program.`，因此未实际创建 `mower-annotator` 环境；测试使用当前可用且已安装依赖的 Python 3.13。源码目标为 Python 3.11，需在正常 Conda 安装上运行 `setup.ps1` 复核。未对完整真实数据进行人工 GUI 回归或大规模性能压测；只读抽查了三张原图。无法识别采集会话的图片须人工设置 `group_id`，少量采集组无法满足指定比例时导出会明确报错。
