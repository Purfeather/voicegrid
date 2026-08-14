# 声格 VoiceGrid 2.0 架构说明

## 进程结构

根目录的 `VoiceGrid 声格.exe` 是无控制台薄启动器：它只根据自身位置校验便携目录结构，并用项目内的 `pythonw.exe` 启动桌面宿主；不封装 Python、前端或模型。`启动测试版.bat` 保留为等价的兼容和排障入口。宿主先取得 Windows 命名互斥锁，再启动独立、轻量的原生品牌启动页进程；启动页在自己的 GUI 消息循环中保持移动、最小化和退出可用。FastAPI、Uvicorn、数据库、监控与托盘随后在后台初始化。

本地 API 就绪后，宿主使用持久 WebView2 配置直接创建隐藏的项目中心。只有 WebView2 文档和 React 核心资源都就绪后才显示主窗口、关闭启动页并创建托盘。启动期间关闭窗口会直接退出；主页面就绪后关闭窗口才隐藏到托盘。命名互斥锁确保连续双击只唤醒已有实例。

服务只监听 `127.0.0.1:7862`。模型保持首次生成时懒加载，启动过程不加载 MOSS 权重。所有可写状态统一位于 `data`：数据库、项目、输出索引、参考资源、日志和缓存分别使用 `data/app.db`、`data/projects`、`data/outputs`、`data/references`、`data/logs` 与 `data/cache`。WebView2 缓存不进入便携分发包。

## 前端结构

- `desktop/frontend/src/app`：路由和全局启动状态
- `desktop/frontend/src/features/projects`：项目中心
- `desktop/frontend/src/features/workbench`：音色、文本、输出和高级参数区
- `desktop/frontend/src/features/modules`：三模块页签、安装状态与固定目录检测
- `desktop/frontend/src/features/voice-design`：音色提示词编排、试听、设计历史和共享音色注册
- `desktop/frontend/src/features/sound-effect`：音效模块静态预览与阶段门控
- `desktop/frontend/src/components`：通用控件、标题栏、硬件浮层和音频波形
- `desktop/frontend/src/services`：API、SSE 和最小桌面桥接
- `desktop/frontend/src/styles`：语义令牌与全局规则
- `desktop/frontend/src/theme`：ThemeDefinition 注册表

项目表单状态与服务资源状态分离。`core`、`projects`、`voices`、`styles`、`runtime` 和 `metrics` 独立加载，项目中心只等待 core + projects；工作台使用路由级懒加载。文本切分由受控输入值直接计算，不依赖失焦或额外按键。波形由真实采样摘要绘制，时间、播放进度和裁剪控件使用独立布局行。

## 数据一致性

SQLite 使用 WAL 模式，保存项目索引、音色、风格、任务、输出历史和运行状态。每个项目另有独立 `project.json`，编码为无 BOM UTF-8。

项目保存流程：获取进程内写锁 → 读取当前版本 → 合并工作区 → 写入唯一临时文件并 fsync → 原子替换项目文件 → 更新 SQLite 索引。即使 SQLite 索引损坏，也可扫描项目文件重建。

音色和输出只通过内部资源 ID 暴露给前端。历史清空默认仅删记录；删除实际文件需要显式参数和二次确认。

## API v2

- `/api/v2/health`：数据库、项目索引和 API 的纯缓存健康状态
- `/api/v2/bootstrap/core`：品牌、版本、语言、模型能力和固定默认值
- `/api/v2/bootstrap`：保留的旧聚合接口，仅用于回滚
- `/api/v2/projects`：创建、打开、自动保存、关闭、恢复和历史
- `/api/v2/voices`：上传、分析、试听资源、保存、重命名、删除和非破坏性裁剪参数
- `/api/v2/styles`：内置及自定义风格管理
- `/api/v2/tasks`：创建、查询、取消和清理
- `/api/v2/runtime`、`/api/v2/system/metrics`：模型生命周期和硬件指标
- `/api/v2/artifacts`：受控试听、下载和打开目录
- `/api/v2/events`：任务、模型和硬件状态 SSE

PyWebView2 桥接只保留窗口控制、启动状态、重试/继续等待、打开日志、选择目录和打开目录；业务数据全部经过本地 API。桥接对象不暴露宿主对象图，避免 pywebview 在冷启动时递归扫描。

## 启动诊断

`startup-lab` 为每轮测试创建临时数据库、项目目录和专用 WebView2 配置。启动轨迹以毫秒级 JSONL 记录 shell、后端导入、数据库、项目恢复、API、前端与 ready 阶段。测试器每 100ms 使用 `SendMessageTimeout(WM_NULL)` 和 `IsHungAppWindow` 检测窗口；单次停顿超过 250ms 时宿主会保存全部 Python 线程栈。

运行期数据统一位于根目录 `data`：数据库、项目、输出、参考上传、日志、缓存与模块安装状态不得回写源码目录。`startup-lab` 仅跟踪测试器源码，其数据库、音频与结果均为可删除的本地生成物。

硬件检测在独立监控线程运行，API 与 SSE 只读取最近缓存。正常数据库直接使用 SQLite 项目索引并在后台核对项目文件；索引重建仅发生在数据库新建、损坏恢复或索引为空时。项目列表使用单次聚合查询返回输出数量和音色名称。

## 推理生命周期

模型首次任务时懒加载。MOSS-TTS 生成模型和 MOSS-Audio-Tokenizer-v2 不同时常驻显存：编码参考音色和解码时让 Tokenizer 进入显存，生成文本音频码时让 4B 模型进入显存。任务执行器固定为单工作线程。

排队任务可立即取消；运行任务在当前文本段结束后检查取消标志。成功时先写工程化输出和 SQLite 历史，再发布完成事件。失败时释放模型与 CUDA 缓存。用户也可在硬件浮层中手动释放模型和显存。

### 可选模型隔离

MOSS-VoiceGenerator 与 MOSS-SoundEffect v2 各自拥有 Python 3.12 环境，主后端不导入其模型依赖。测试版的 `models` 目录连接保持只读，可选模型固定写入测试版独立的 `optional-models`。自动安装先创建临时运行环境和临时模型目录，核对 ModelScope 固定清单、实际文件数量和总大小后再原子替换。音色设计工作进程通过 UTF-8 JSON 行协议通信；切换回语音合成前释放该进程，反向切换前释放 MOSS-TTS 模型。

项目 schema 4 使用 `workspaces.speech`、`workspaces.voice_design` 与 `workspaces.sound_effect` 分别保存草稿。任务与输出带 `module` 和 `kind`，各页签只读取自己的活动记录。音色设计成品位于项目受控目录，显式命名后复制到全局音色库；音效素材将保存在当前项目范围内。

## 编码与边界

- BAT/CMD：纯 ASCII、CRLF
- Python/TypeScript/JSON/CSS/HTML/Markdown/TXT/LOG：无 BOM UTF-8
- 自动化命令行不直接传中文值，改用 ASCII Unicode 转义
- 正式 1.0、模型连接目标和模型权重只读
- 当前版本为 `2.0.0-dev`，不包含正式分发构建；`v1.0.0-beta.1` 保留为单模块冻结基线
