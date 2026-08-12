# 启动响应实验区

这里用于验证桌面宿主和独立品牌启动页的启动响应，不读取或修改正式项目数据。每个用例都创建临时 SQLite、临时项目目录和独立 WebView2 配置，模型仍保持懒加载。

## 测试套件

- `quick`：分别以 0、1、50、200 个项目启动，并检查一次后台实例唤醒。
- `faults`：覆盖数据库损坏恢复、端口占用、后端导入、硬件检测、托盘和 WebView2 故障。
- `acceptance`：20 次冷启动、20 次热启动和 20 次实例唤醒。

每 100ms 使用 `SendMessageTimeout(WM_NULL)` 和 `IsHungAppWindow` 检查窗口。宿主内部也执行同样的监测；超过 250ms 会把所有 Python 线程栈写入临时日志。每轮还会连续测量 10 次 `/api/v2/health`、比较 Windows WER 的 AppHang 1001/1002 事件，并验证退出后端口已释放。

结果写入 `startup-lab/results`。该目录只保存测试报告，不保存用户项目、音色或输出。

## 运行

```powershell
.venv\Scripts\python.exe startup-lab\run_startup_lab.py --suite quick
.venv\Scripts\python.exe startup-lab\run_startup_lab.py --suite faults
.venv\Scripts\python.exe startup-lab\run_startup_lab.py --suite acceptance
```
