# Windows EXE 打包验收记录

日期：2026-10-13（Asia/Shanghai）。目标环境：Windows 11；打包环境：`mower-annotator`，Python 3.11.17、PyInstaller 6.22.3、PySide6 6.12.0、Pillow 12.3.0。

## 交付物

`dist/MowerAnnotator.exe`，56,257,897 字节（约 53.65 MiB）。SHA256：`B8D2D3B56EDF7180E41FAAA054C51027DB1420140EF0E22A21951FCCDDF3CE04`。PE Subsystem 为 2（Windows GUI），构建设置 `console=False`。

## 实际执行的自动化验证

| 项目 | 结果 |
|---|---|
| Python 3.11 源码测试：`python -m pytest -q --basetemp=.pytest_tmp` | 17 passed，0 failed |
| Python 编译检查、`build_exe.ps1` 的 PowerShell 语法检查 | 通过 |
| onedir 包自检 | 通过，见 `EXE_ONEDIR_TEST_REPORT.json` |
| onefile EXE 自检 | 通过，见 `EXE_BUILD_TEST_REPORT.json` |
| onefile 从非源码工作目录启动并运行完整自检 | 通过，见 `EXE_OTHER_CWD_REPORT.json` |
| onefile 正常 GUI 入口启动、进程在 4 秒后仍运行 | 通过；随后主动结束测试进程 |
| bundled `classes.yaml` 与源码的类别配置哈希 | 一致：`82cae6248f857b53d93fb8998add67904c7857cda6b8dbdec57c137fe55a581e` |

封装自检使用临时生成的中文及空格路径图片，实际执行：GUI 绘框、改类、保存并进入下一张；项目重开恢复；negative 与 unreviewed 检查；创建两份 Worker Package 并合并 Master；导出 YOLO，检查 negative 空标签及 unreviewed 排除。测试目录自动清理，不接触真实原图和用户标注。

## 人工验收状态与步骤

本次没有在可见桌面上逐项手动点击最终 EXE；现有源码版此前已由用户人工功能检查。最终 EXE 在发给标注人员前，建议由维护人员在另一台 Windows 11 电脑做以下人工回归：

1. 双击 EXE，确认中文窗口出现且没有控制台。
2. 用几张复制到临时目录的图片新建项目，画框、拖动调整、改类别、按 Space 保存切图。
3. 关闭并重新打开项目，检查框、类别和状态一致。
4. 按 N 确认空图，跳过另一张图，查看检查窗口的未标注列表。
5. 生成两份测试 Worker Package，合并；对不同标注制造冲突，确认需人工选择后才可生成 Master。
6. 导出 YOLO，查看 `data.yaml`、图片与标签文件一一对应。
7. 在非管理员账户及含中文、空格的路径下重试一次，并确认保存失败时的日志路径可写。

## 已知兼容性注意事项

打包环境曾把不兼容的 ICU 78 DLL 混入 Qt，导致启动失败；正式 spec 已排除它，Windows 11 自带的 ICU 接口在本机通过验证。仍需在其他 Windows 11 版本和安全软件配置下验证首次解压、Qt 图形驱动及文件访问权限。onefile 启动会在用户临时目录解压，磁盘空间不足或安全软件拦截可能阻止启动。没有做跨电脑人工回归，不能把本机自动化结果表述为跨电脑验证通过。

## 重新打包

在开发电脑中运行 `build_exe.ps1`。脚本查找现有 `mower-annotator` 环境，仅在缺 PyInstaller 时安装它；默认依次构建 onedir 验证包和正式 onefile EXE，完成后输出路径、字节数与报告。维护人员若已单独完成 onedir 诊断，可使用 `build_exe.ps1 -SkipOnedir`。正式配置为 `MowerAnnotator.spec`，诊断配置为 `MowerAnnotatorProbe.spec`。普通标注人员只需双击 EXE，不需运行脚本。
