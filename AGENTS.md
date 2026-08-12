# 测试版开发边界

- 当前目录 `D:\MOSS-TTS-Test-Version` 是新版唯一开发目录。
- `D:\MOSS-TTS-v1.5-Portable` 是正式 1.0，禁止在其中新增、修改或删除开发文件。
- `models` 是指向正式模型文件的只读目录连接；不要移动、覆盖或删除其目标。
- `.venv` 是测试版自己的轻量环境。新增依赖必须通过当前目录下的 `.venv` 安装。
- 正式打包前，再把模型和完整 Python 运行环境复制进测试版构建目录，解除共享依赖。

## 编码与 Windows 启动脚本硬性规则

- 项目自有的 `.bat` 和 `.cmd` 文件必须同时满足：纯 ASCII 内容、Windows CRLF 换行。批处理正文禁止出现中文、UTF-8 BOM 或仅 LF 换行；中文错误提示应由 Python 窗口或日志承担。
- Python、JSON、HTML、CSS、JavaScript、Markdown 和文本配置统一使用无 BOM 的 UTF-8。读取时必须显式指定 UTF-8，禁止依赖 Windows PowerShell 的默认编码。
- 自动化命令行中禁止直接嵌入中文参数；接口回归、路径外的中文测试值一律使用 ASCII 的 `\uXXXX` 转义或从无 BOM UTF-8 文件读取，避免控制台代码页污染数据。
- 禁止使用 `echo`、默认 `Set-Content`、默认 `Out-File` 等方式重写源码或批处理；必须保留并验证目标文件的编码与换行格式。
- 每次修改启动器、文本资源或前端源码后，必须执行：`.venv\Scripts\python.exe -m unittest discover -s desktop/tests -v`。
- 编码测试失败时不得交付或继续启动验证，必须先修复被报告的文件。
