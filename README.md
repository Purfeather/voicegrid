# 龙融影业 AI 配音台 2.0（开发测试版）

这是完全脱离 Gradio 的本地桌面配音工作站。界面使用 React + TypeScript，后端使用 FastAPI + SQLite，桌面窗口由 PyWebView2 承载。内部版本为 `2.0.0-dev`，尚未进入 EXE 或 ZIP 分发阶段。

## 启动

双击根目录的 `启动测试版.bat`。程序会先显示可响应的龙融影业品牌启动页，再进入项目中心；正常启动不会预加载模型或占用额外显存。关闭主窗口只会隐藏到系统托盘；再次双击启动器会唤醒现有窗口。只有右键托盘图标并选择“退出”才会结束后台服务和模型进程。

若准备时间超过 5 秒，启动页会显示真实阶段及“继续等待、重试、打开日志、退出”。内部回滚入口为 `internal-rollback-legacy.bat`，仅用于开发排障。

## 当前模型与预设

- MOSS-TTS-Local-Transformer-v1.5 4B
- MOSS-Audio-Tokenizer-v2
- 标准：400 字、120 秒，默认启用
- 兼容：90 字、20 秒
- 完全离线加载；CUDA 上按设备能力使用 BF16/FP16、SDPA，并让生成模型与 Audio Tokenizer 分阶段进入显存

## 数据位置

- 项目文件：`projects/<project-id>/project.json`
- SQLite 索引：`data/app.db`
- 音色库：`data/voices`
- 临时上传：`data/uploads`
- 项目输出：每个项目自己的 `outputs` 目录，或用户选择的目录
- 旧版归档：`archive/pre-rebuild-20260811`

项目文件是可恢复的事实来源；SQLite 索引可从项目文件重建。历史记录默认只清除数据库记录，只有再次确认才会删除音频文件。

## 开发与验证

- 前端构建：在 `desktop/frontend` 中运行 `npm.cmd run build`
- 前端测试：在 `desktop/frontend` 中运行 `npm.cmd test -- --run`
- 后端测试：运行 `.venv\Scripts\python.exe -m unittest discover -s desktop\tests -v`
- 启动快速回归：运行 `.venv\Scripts\python.exe startup-lab\run_startup_lab.py --suite quick`
- 启动完整验收：运行 `.venv\Scripts\python.exe startup-lab\run_startup_lab.py --suite acceptance`

正式 1.0 目录和 `models` 连接目标只读，禁止在其中新增、修改或删除开发文件。详细架构见 `ARCHITECTURE.md`，界面规范见 `design-system/longrong-ai-voice-studio/MASTER.md`。
