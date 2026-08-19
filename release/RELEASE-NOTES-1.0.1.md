# 声格 VoiceGrid 1.01（内部版本 1.0.1）

发布日期：2026-08-18
构建编号：`VOICEGRID-1.0.1-20260818`

## 发布内容

- 标准便携版：包含应用与便携运行环境，不包含模型；三个模块可在软件内按需安装。
- 完整离线版：包含语音合成、音色设计和音效生成所需模型与独立运行环境。
- 源代码包：包含 Git 跟踪源码、构建脚本、依赖清单、图标母版及开源许可文件。

## 开源许可

VoiceGrid 自有代码与资产采用 MIT License，完整版权与许可文本见根目录 `LICENSE`。

“声格 VoiceGrid”名称和 Logo 不随 MIT 许可证授权。模型权重、第三方运行库与生成内容分别遵循其各自许可。

## 产物校验

- 标准版：`VoiceGrid-1.0.1-Standard.zip`
  - SHA-256：构建后写入 `artifacts/SHA256SUMS.txt`
- 源代码包：`VoiceGrid-1.0.1-Source.zip`
  - SHA-256 见发布目录中的 `SHA256SUMS.txt`。
- 完整离线版：`staging/VoiceGrid-1.0.1-Offline（未压缩文件夹）`
  - 文件级 SHA-256 见 `reports/VoiceGrid-1.0.1-Offline-FILES-SHA256.txt`。
  - 同时提供 ZIP 格式 4 GiB 分卷：`VoiceGrid-1.0.1-Offline.zip.001`、`.002` 等，全部分卷均列入 `artifacts/SHA256SUMS.txt`。

## 签名说明

- 启动器：`VoiceGrid 声格.exe`
- 证书主题：`CN=VoiceGrid`
- 证书指纹：见 `reports/SIGNING-INFO.txt`
- 签名算法：RSA 3072 / SHA-256
- 时间戳：DigiCert SHA-256 时间戳服务

该签名使用发布时生成的自签名代码签名证书，可用于核对文件是否与本次发行一致，但不会自动消除 Windows SmartScreen 的“未知发布者”提示。

## 验收结果

- 103 项后端测试、9 项身份与图标测试、23 项前端测试全部通过。
- TypeScript、生产构建、API 契约、编码换行、语义颜色和 Git 空白检查通过。
- 标准版在干净目录解压后启动器验证通过，三个模块均正确显示为未安装。
- 完整离线版在干净目录解压后，三个模块均检测为已安装且可用。
- 音色设计、共享音色到语音合成链路、音效生成实机冒烟测试通过。
- 标准版和源代码包通过 ZIP/ZIP64 完整性测试；完整离线版文件夹通过目录验收，ZIP 分卷通过分卷完整性测试。
- 发布包不包含项目、生成历史、输出音频、共享音色、上传参考、自定义风格、缓存或日志。
