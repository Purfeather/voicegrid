# 声格 VoiceGrid 1.0

声格 VoiceGrid 是一套本地桌面音频工作站。界面使用 React + TypeScript，后端使用 FastAPI + SQLite，桌面窗口由 PyWebView2 承载。当前正式版本为 `1.0.0`。

## 开源许可

VoiceGrid 自有代码以 [MIT License](LICENSE) 开源，允许使用、修改、商用和再分发，但必须保留版权与许可文本。“声格 VoiceGrid”名称和 Logo 不随 MIT 许可证授权；修改版不得冒充官方发行版或暗示获得官方认可，具体见 `LICENSES/VoiceGrid-商标与官方发行说明.txt`。

MOSS 模型权重、Python 运行环境及其他第三方组件不自动适用 MIT，须分别遵守其上游许可证。用户生成的音频也不会因为软件采用 MIT 而自动成为开源内容。

运行期可写内容统一保存在 `data` 目录；根目录的 `optional-models` 与 `runtimes` 只保存可选模型和隔离运行环境，`models` 继续作为只读模型连接。

## 启动

双击根目录的 `VoiceGrid 声格.exe`。程序会先显示可响应的产品启动页，再进入项目中心；正常启动不会预加载模型或占用额外显存。桌面快捷方式应指向根目录中的 EXE，不要单独复制 EXE。`备用启动.bat` 继续保留为兼容和排障入口。关闭主窗口只会隐藏到系统托盘；再次双击启动器会唤醒现有窗口。只有右键托盘图标并选择“退出”才会结束后台服务和模型进程。

若准备时间超过 5 秒，启动页会显示真实阶段及“继续等待、重试、打开日志、退出”。内部回滚入口为 `internal-rollback-legacy.bat`，仅用于开发排障。

## 当前模型与预设

- MOSS-TTS-Local-Transformer-v1.5 4B
- MOSS-Audio-Tokenizer-v2
- 标准：400 字、120 秒，默认启用
- 兼容：90 字、20 秒
- 完全离线加载；CUDA 上按设备能力使用 BF16/FP16、SDPA，并让生成模型与 Audio Tokenizer 分阶段进入显存

## 三模块工作台

- 语音合成：保留现有 MOSS-TTS 1.5 4B 完整工作流。
- 音色设计：MOSS-VoiceGenerator 与 MOSS-Audio-Tokenizer 独立安装；支持八类提示词模块组合、自由描述、最终提示词显式应用、项目历史与“保存为音色”。
- 音效生成：MOSS-SoundEffect v2.0 页面和可选安装入口已分离；真实推理按阶段验收，当前未安装时仍可完整预览。

可选模块不会在启动或切换页签时下载、导入或占用显存。用户确认后才会从 ModelScope 下载固定清单，并安装到 `optional-models` 与 `runtimes`；这两个目录不进入 Git，也不进入标准便携版，但会按各自上游许可证纳入完整离线版。测试版的 `models` 是指向正式模型库的只读连接，因此发布构建不会跟随或修改该连接。模型运行于独立隐藏进程，三个模块共享同一条串行 GPU 任务队列。

## 数据位置

- 项目文件：`projects/<project-id>/project.json`
- SQLite 索引：`data/app.db`
- 音色库：`data/voices`
- 临时上传：`data/uploads`
- 项目输出：`data/projects/<项目ID>/outputs` 下的模块固定目录
- 旧版归档：`archive/pre-rebuild-20260811`

项目文件是可恢复的事实来源；SQLite 索引可从项目文件重建。历史记录默认只清除数据库记录，只有再次确认才会删除音频文件。

## 开发与验证

- 前端构建：在 `desktop/frontend` 中运行 `npm.cmd run build`
- 介绍官网：在 `website` 中运行 `npm.cmd install`、`npm.cmd test` 与 `npm.cmd run build`
- 完整质量检查：运行根目录 `quality-check.bat`，依次验证编码、后端、前端、API 类型、设计令牌、构建产物与 Git 差异
- 前端测试：在 `desktop/frontend` 中运行 `npm.cmd test -- --run`
- 后端测试：运行 `.venv\Scripts\python.exe -m unittest discover -s desktop\tests -v`
- 启动快速回归：运行 `.venv\Scripts\python.exe startup-lab\run_startup_lab.py --suite quick`
- 启动完整验收：运行 `.venv\Scripts\python.exe startup-lab\run_startup_lab.py --suite acceptance`

从源码构建前端时，在 `desktop/frontend` 执行 `npm.cmd ci` 与 `npm.cmd run build`。后端使用 Python 3.12，并按 `requirements.txt` 安装依赖。发布构建使用 `release/build_release.py` 生成标准版、完整离线版和源代码包。

欢迎通过正式源代码仓库提交问题与改进。贡献内容在提交时应确保有权按项目的 MIT License 提供。

正式 1.0 目录和 `models` 连接目标只读，禁止在其中新增、修改或删除开发文件。详细架构见 `ARCHITECTURE.md`，界面规范见 `design-system/voicegrid/MASTER.md`。
