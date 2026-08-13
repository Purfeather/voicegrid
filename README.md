# 声格 VoiceGrid 2.0（开发测试版）

声格 VoiceGrid 是龙融影业的本地桌面音频工作站，作者为 Wang Xiaohan。界面使用 React + TypeScript，后端使用 FastAPI + SQLite，桌面窗口由 PyWebView2 承载。当前多模块开发版本为 `2.0.0-dev`；上一个可回退冻结点为 `v1.0.0-beta.1`。

## 启动

双击根目录的 `声格 VoiceGrid.exe`。程序会先显示可响应的龙融影业品牌启动页，再进入项目中心；正常启动不会预加载模型或占用额外显存。桌面快捷方式应指向根目录中的 EXE，不要单独复制 EXE。`启动测试版.bat` 继续保留为兼容和排障入口。关闭主窗口只会隐藏到系统托盘；再次双击启动器会唤醒现有窗口。只有右键托盘图标并选择“退出”才会结束后台服务和模型进程。

若准备时间超过 5 秒，启动页会显示真实阶段及“继续等待、重试、打开日志、退出”。内部回滚入口为 `internal-rollback-legacy.bat`，仅用于开发排障。

## 当前模型与预设

- MOSS-TTS-Local-Transformer-v1.5 4B
- MOSS-Audio-Tokenizer-v2
- 标准：400 字、120 秒，默认启用
- 兼容：90 字、20 秒
- 完全离线加载；CUDA 上按设备能力使用 BF16/FP16、SDPA，并让生成模型与 Audio Tokenizer 分阶段进入显存

## 2.0 多模块预览

- 语音合成：保留现有 MOSS-TTS 1.5 4B 完整工作流。
- 音色设计：MOSS-VoiceGenerator 与 MOSS-Audio-Tokenizer 独立安装；支持八类提示词模块组合、自由描述、最终提示词显式应用、项目历史与“保存为音色”。
- 音效生成：MOSS-SoundEffect v2.0 页面和可选安装入口已分离；真实推理按阶段验收，当前未安装时仍可完整预览。

可选模块不会在启动或切换页签时下载、导入或占用显存。用户确认后才会从 ModelScope 下载固定清单，并安装到 `optional-models` 与 `runtimes`；这两个目录不进入 Git 或便携包。测试版的 `models` 是指向正式模型库的只读连接，因此可选权重刻意使用独立目录，避免修改正式版。模型运行于独立隐藏进程，三个模块共享同一条串行 GPU 任务队列。

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
