# VoiceGrid 1.0.2 发布构建

发布构建只允许写入 D:\VoiceGrid-Release，不会修改正式版目录或模型连接。

1. 运行项目根目录的 quality-check.bat。
2. 运行 .venv\Scripts\python.exe desktop\launcher\build_launcher.py。
3. 运行 powershell -ExecutionPolicy Bypass -File release\sign_release.ps1。
4. 运行 .venv\Scripts\python.exe release\build_release.py all。
5. 从 D:\VoiceGrid-Release\artifacts 解压标准版和源码包；完整离线版直接验收 staging\VoiceGrid-1.0.2-Offline 文件夹。

标准版和源码包使用 Python 内置 ZIP/ZIP64 格式生成并完成完整性测试，不依赖额外压缩软件。

离线版同时生成 ZIP 格式的 4 GiB 分卷：

`D:\VoiceGrid-Release\artifacts\VoiceGrid-1.0.2-Offline.zip.001`、`.002` 等。分发时必须保留全部分卷，从 `.zip.001` 开始解压；
完整离线文件夹仍保留在 `staging` 中用于直接验收。

标准版不包含模型；完整离线版复制开发版已经验收的五套模型，并将主环境和
两个可选环境重建为无 pyvenv.cfg 的便携 Python 3.12。源代码包不包含模型、
运行时、EXE和前端编译产物。

自签名证书私钥在签名完成后删除，不生成PFX。公开证书、指纹和签名说明保存在
D:\VoiceGrid-Release\certificates 与 reports。
