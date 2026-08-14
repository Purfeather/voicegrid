# VoiceGrid 1.0 发布构建

发布构建只允许写入 D:\VoiceGrid-Release，不会修改正式版目录或模型连接。

1. 运行项目根目录的 quality-check.bat。
2. 运行 .venv\Scripts\python.exe desktop\launcher\build_launcher.py。
3. 运行 powershell -ExecutionPolicy Bypass -File release\sign_release.ps1。
4. 运行 .venv\Scripts\python.exe release\install_7zip_tool.py。
5. 运行 .venv\Scripts\python.exe release\build_release.py all。
6. 从 D:\VoiceGrid-Release\artifacts 解压三套产物进行最终回归。

标准版不包含模型；完整离线版复制开发版已经验收的五套模型，并将主环境和
两个可选环境重建为无 pyvenv.cfg 的便携 Python 3.12。源代码包不包含模型、
运行时、EXE和前端编译产物。

自签名证书私钥在签名完成后删除，不生成PFX。公开证书、指纹和签名说明保存在
D:\VoiceGrid-Release\certificates 与 reports。
