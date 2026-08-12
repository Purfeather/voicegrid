import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Cpu, Gauge, Maximize2, MemoryStick, Minus, Moon, Power, Square, Sun, X } from "lucide-react";
import type { HardwareMetrics, RuntimeSnapshot, ThemeId } from "../types";
import { windowAction } from "../services/native";
import { Badge, Button, IconButton } from "./UI";
import styles from "./titlebar.module.css";

interface Props {
  projectName?: string;
  saveState?: string;
  runtime: RuntimeSnapshot;
  metrics: HardwareMetrics;
  theme: ThemeId;
  onTheme: (theme: ThemeId) => void;
  onBack?: () => void;
  onRelease: () => Promise<void>;
  startupMode?: boolean;
}

function HardwarePopover({ metrics, runtime, onRelease, onClose }: { metrics: HardwareMetrics; runtime: RuntimeSnapshot; onRelease: () => Promise<void>; onClose: () => void }) {
  return (
    <aside className={styles.hardwarePopover} aria-label="运行环境详情">
      <header><div><span>本机运行环境</span><strong>{runtime.active_model ? "模型已接入" : "模型待命"}</strong></div><IconButton label="关闭硬件详情" onClick={onClose}><X size={17} /></IconButton></header>
      <div className={styles.metricGrid}>
        <div><Cpu size={17} /><span>CPU</span><strong>{metrics.cpu_percent.toFixed(0)}%</strong></div>
        <div><MemoryStick size={17} /><span>内存</span><strong>{metrics.memory_used_gb.toFixed(1)} / {metrics.memory_total_gb.toFixed(1)} GB</strong></div>
        <div><Gauge size={17} /><span>GPU</span><strong>{metrics.gpu_percent == null ? "--" : `${metrics.gpu_percent.toFixed(0)}%`}</strong></div>
        <div><MemoryStick size={17} /><span>显存</span><strong>{metrics.vram_used_gb == null ? "--" : `${metrics.vram_used_gb.toFixed(1)} / ${metrics.vram_total_gb?.toFixed(1)} GB`}</strong></div>
      </div>
      <dl className={styles.environmentList}>
        <div><dt>显卡</dt><dd>{metrics.gpu_name || "未检测到"}</dd></div>
        <div><dt>模型</dt><dd>MOSS-TTS Local Transformer v1.5 · 4B</dd></div>
        <div><dt>设备</dt><dd>{runtime.device || "待检测"} · {runtime.dtype || "--"} · {runtime.attention || "--"}</dd></div>
        <div><dt>环境</dt><dd>Python {metrics.python_version} · {metrics.platform}</dd></div>
      </dl>
      <Button variant="secondary" icon={<Power size={15} />} onClick={onRelease} disabled={runtime.state === "idle"}>释放模型与显存</Button>
    </aside>
  );
}

export function TitleBar({ projectName, saveState, runtime, metrics, theme, onTheme, onBack, onRelease, startupMode = false }: Props) {
  const [hardwareOpen, setHardwareOpen] = useState(false);
  const hardwareRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!hardwareOpen) return;
    const close = (event: MouseEvent) => {
      if (!hardwareRef.current?.contains(event.target as Node)) setHardwareOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [hardwareOpen]);

  const runtimeTone = runtime.state === "running" ? "accent" : runtime.state === "error" ? "danger" : runtime.state === "loaded" ? "success" : "neutral";
  return (
    <header className={styles.titlebar}>
      {onBack && <IconButton label="返回项目中心" className={styles.noDrag} onClick={onBack}><ArrowLeft size={18} /></IconButton>}
      <div className={`${styles.dragRegion} pywebview-drag-region`} onDoubleClick={() => windowAction("maximize")}>
        <img src="/api/v2/brand/icon" alt="龙融影业" />
        <div className={styles.brand}><strong>龙融影业</strong><span>AI 配音台 2.0</span></div>
        {projectName && <><i className={styles.divider} /><div className={styles.project}><strong>{projectName}</strong><span>{saveState || "自动保存已开启"}</span></div></>}
      </div>
      <div className={styles.tools}>
        <Badge tone={runtimeTone}>{runtime.message}</Badge>
        <div className={styles.hardwareAnchor} ref={hardwareRef}>
          <button className={styles.hardwareButton} aria-expanded={hardwareOpen} onClick={() => setHardwareOpen((value) => !value)}>
            <Gauge size={15} /><span>{metrics.gpu_name || "运行环境"}</span><strong>{metrics.vram_used_gb == null ? "--" : `${metrics.vram_used_gb.toFixed(1)}G`}</strong>
          </button>
          {hardwareOpen && <HardwarePopover metrics={metrics} runtime={runtime} onRelease={onRelease} onClose={() => setHardwareOpen(false)} />}
        </div>
        <div className={styles.themeSwitch} role="radiogroup" aria-label="界面主题">
          <button className={theme === "dark" ? styles.active : ""} role="radio" aria-checked={theme === "dark"} title="炭黑荧光" onClick={() => onTheme("dark")}><Moon size={15} /></button>
          <button className={theme === "light" ? styles.active : ""} role="radio" aria-checked={theme === "light"} title="纯白 AI" onClick={() => onTheme("light")}><Sun size={15} /></button>
        </div>
        <div className={styles.windowControls}>
          <IconButton label="最小化" onClick={() => windowAction("minimize")}><Minus size={17} /></IconButton>
          <IconButton label="最大化或还原" onClick={() => windowAction("maximize")}><Maximize2 size={15} /></IconButton>
          <IconButton label={startupMode ? "退出启动" : "隐藏到托盘"} className={styles.closeButton} onClick={() => windowAction(startupMode ? "exit" : "hide")}><X size={18} /></IconButton>
        </div>
      </div>
    </header>
  );
}
