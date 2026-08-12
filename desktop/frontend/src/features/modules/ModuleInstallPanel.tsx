import { useState } from "react";
import { CheckCircle2, Download, FolderCog, HardDrive, RefreshCw, ShieldCheck, Wrench } from "lucide-react";
import type { ModuleDescriptor } from "../../types";
import { Badge, Button, Modal, Progress } from "../../components/UI";
import styles from "./modules.module.css";

function formatBytes(value: number) { return `${(value / 1024 ** 3).toFixed(1)} GB`; }

export function ModuleInstallPanel({ module, onDetect, onInstall }: { module: ModuleDescriptor; onDetect: () => Promise<void>; onInstall: (repair: boolean) => Promise<void> }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const installing = module.install_state === "installing";
  const repair = module.install_state === "repair_required" || module.install_state === "failed";
  async function run(action: () => Promise<void>) { setBusy(true); try { await action(); } finally { setBusy(false); } }

  if (module.installed) return (
    <section className={styles.installReady}>
      <CheckCircle2 size={18} /><div><strong>模块已安装</strong><span>{module.model_name} 与{module.runtime_mode === "host" ? "主程序环境" : "独立环境"}均已检测到</span></div>
      <Button variant="ghost" icon={<RefreshCw size={14} />} busy={busy} onClick={() => run(onDetect)}>重新检测</Button>
    </section>
  );
  return <>
    <section className={styles.installPanel}>
      <header><div><span>MODULE STATUS</span><strong>{repair ? "安装需要修复" : "模型尚未安装"}</strong></div><Badge tone={repair ? "warning" : "neutral"}>可预览界面</Badge></header>
      <p>{module.description}</p>
      {installing ? <div className={styles.installProgress}><Progress value={module.install_progress} label="安装进度" /><span>{module.install_message}</span></div> : <div className={styles.installActions}>
        <Button variant="primary" icon={repair ? <Wrench size={15} /> : <Download size={15} />} onClick={() => setConfirmOpen(true)}>{repair ? "安装 / 修复" : "自动安装"}</Button>
        <Button variant="secondary" icon={<RefreshCw size={15} />} busy={busy} onClick={() => run(onDetect)}>重新检测</Button>
      </div>}
      {module.error && <small className={styles.installError}>{module.error}</small>}
      <div className={styles.manualPaths}><FolderCog size={14} /><span>也可手动放入固定目录后重新检测</span></div>
    </section>
    <Modal open={confirmOpen} title={`${repair ? "修复" : "安装"}${module.name}`} onClose={() => setConfirmOpen(false)} footer={<><Button variant="ghost" onClick={() => setConfirmOpen(false)}>取消</Button><Button variant="primary" icon={<Download size={15} />} busy={busy} onClick={() => run(async () => { await onInstall(repair); setConfirmOpen(false); })}>确认并开始</Button></>}>
      <div className={styles.installConfirm}>
        <div><HardDrive size={18} /><span>下载 / 临时峰值</span><strong>{module.download_gb.toFixed(1)} / {module.required_disk_gb.toFixed(1)} GB</strong></div>
        <div><ShieldCheck size={18} /><span>来源与版本</span><strong>ModelScope · 固定清单</strong></div>
        <div><FolderCog size={18} /><span>运行环境</span><strong>{module.runtime_python}</strong></div>
        <p>安装只会在你确认后开始。模型与音频分词器保存在测试版独立目录；{module.runtime_mode === "host" ? "继续复用主程序运行环境" : "依赖使用模块专属运行环境"}，不会修改正式版模型。</p>
        <ul>{module.manual_paths.map((path) => <li key={path}>{path}</li>)}</ul>
        <small>{module.model_locks.map((lock) => `${lock.model_id}（${formatBytes(lock.total_bytes)}）`).join("；")}</small>
      </div>
    </Modal>
  </>;
}
