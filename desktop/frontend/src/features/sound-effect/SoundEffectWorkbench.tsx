import { useEffect, useState } from "react";
import { AudioLines, Download, FolderOpen, Heart, LockKeyhole, Sparkles } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import type { HardwareMetrics, ModuleDescriptor, ProjectDetail, RuntimeSnapshot, SoundEffectDraft, ThemeId } from "../../types";
import { api } from "../../services/api";
import { TitleBar } from "../../components/TitleBar";
import { Badge, Button, EmptyState, Field, Section, TextArea, TextInput } from "../../components/UI";
import { ModuleInstallPanel } from "../modules/ModuleInstallPanel";
import { ModuleTabs } from "../modules/ModuleTabs";
import { OptionalModuleColumn, OptionalModuleWorkbench } from "../modules/OptionalModuleWorkbench";
import { AssetLibrary, ModuleActivityTimeline, ModuleCurrentOutput, ModuleGenerateCard, ModuleParameterRail } from "../modules/ModuleWorkbenchShell";
import styles from "./soundEffect.module.css";

interface Props {
  modules: ModuleDescriptor[];
  runtime: RuntimeSnapshot;
  metrics: HardwareMetrics;
  theme: ThemeId;
  onTheme: (theme: ThemeId) => void;
  onModulesChanged: () => Promise<void>;
  onRuntime: (runtime: RuntimeSnapshot) => void;
  onMessage: (message: string, tone?: "success" | "error") => void;
}

export function SoundEffectWorkbench(props: Props) {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const module = props.modules.find((item) => item.id === "sound_effect");
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [draft, setDraft] = useState<SoundEffectDraft | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [loadError, setLoadError] = useState("");
  const interactive = Boolean(module?.installed && module.engine_available);

  useEffect(() => {
    api.openProject(projectId).then((detail) => {
      setProject(detail);
      setDraft(detail.workspaces.sound_effect);
    }).catch((error) => setLoadError(error instanceof Error ? error.message : "项目载入失败"));
  }, [projectId]);

  function update(patch: Partial<SoundEffectDraft>) {
    if (!interactive) return;
    setDraft((current) => current ? { ...current, ...patch } : current);
  }

  async function closeProject() {
    try { if (project) await api.closeProject(project.id); } catch { /* Recovery remains available. */ }
    navigate("/projects");
  }

  if (loadError || !project || !draft) return <><TitleBar runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={() => navigate("/projects")} onRelease={async () => props.onRuntime(await api.releaseRuntime())} /><ModuleTabs modules={props.modules} /><main className={styles.loading}><EmptyState title={loadError ? "项目无法打开" : "正在准备音效模块"} detail={loadError || "正在载入项目中的音效工作区…"} /></main></>;

  return <>
    <TitleBar projectName={project.name} saveState="预览模式 · 未保存" runtime={props.runtime} metrics={props.metrics} theme={props.theme} onTheme={props.onTheme} onBack={closeProject} onRelease={async () => props.onRuntime(await api.releaseRuntime())} />
    <ModuleTabs modules={props.modules} />
    <OptionalModuleWorkbench label="音效生成工作台" parameterRail={<ModuleParameterRail open={advancedOpen} onOpen={setAdvancedOpen} title="高级生成参数" summary={`稳定模式 · ${draft.parameters.num_inference_steps} 步 · CFG ${draft.parameters.cfg_scale} · Sigma ${draft.parameters.sigma_shift}`} locked={!interactive}>
      <fieldset className={styles.railParameterGrid} disabled={!interactive}>
        <Field label="推理步数" help="默认 100，范围 10–150"><TextInput type="number" min="10" max="150" value={draft.parameters.num_inference_steps} onChange={(e) => update({ parameters: { ...draft.parameters, num_inference_steps: Number(e.target.value) } })} /></Field>
        <Field label="CFG" help="默认 4.0，范围 1–8"><TextInput type="number" min="1" max="8" step="0.1" value={draft.parameters.cfg_scale} onChange={(e) => update({ parameters: { ...draft.parameters, cfg_scale: Number(e.target.value) } })} /></Field>
        <Field label="Sigma Shift" help="默认 5.0，范围 0–10"><TextInput type="number" min="0" max="10" step="0.1" value={draft.parameters.sigma_shift} onChange={(e) => update({ parameters: { ...draft.parameters, sigma_shift: Number(e.target.value) } })} /></Field>
        <Field label="随机种子"><TextInput type="number" min="0" value={draft.parameters.seed} onChange={(e) => update({ parameters: { ...draft.parameters, seed: Number(e.target.value) } })} /></Field>
      </fieldset>
    </ModuleParameterRail>}>
      <OptionalModuleColumn label="音效模块状态">
        {module && <ModuleInstallPanel module={module} onDetect={async () => { await api.detectModule("sound_effect"); await props.onModulesChanged(); }} onInstall={async (repair) => { await api.installModule("sound_effect", repair); await props.onModulesChanged(); props.onMessage("音效模型安装已在后台开始。", "success"); }} />}
        <section className={styles.stageNotice}><LockKeyhole size={18} /><div><strong>推理接入暂未开放</strong><span>{module?.engine_message || "音色设计验收通过后，再接入 MOSS-SoundEffect-v2.0 真实推理。"}</span></div></section>
        <AssetLibrary title="项目音效素材库" eyebrow="Project SFX library" count={<Badge tone="neutral">0 个</Badge>}>
          <div className={styles.assetList}>{["雨夜远处车辆驶过", "金属门缓慢开启", "林间风吹树叶"].map((name, index) => <article key={name}><span><AudioLines size={15} /></span><div><strong>{name}</strong><small>示例内容 · {8 + index * 3} 秒</small></div><Heart size={14} /><em>WAV</em></article>)}</div>
          <EmptyState title="安装后建立项目素材库" detail="真实结果将自动进入当前项目，支持试听、收藏、重命名、下载和删除。" />
        </AssetLibrary>
      </OptionalModuleColumn>

      <OptionalModuleColumn label="音效描述与参数">
        <Section title="声音场景" eyebrow="SOUND BRIEF" actions={<Badge tone="neutral">1–30 秒</Badge>}>
          <div className={styles.sectionBody}>
            <Field label="自由提示词" help="描述环境、声源、距离、动作、材质和时间变化。"><TextArea disabled={!interactive} rows={10} value={draft.prompt} onChange={(event) => update({ prompt: event.target.value })} /></Field>
            <Field label="生成时长"><div className={styles.durationField}><input disabled={!interactive} type="range" min="1" max="30" step="1" value={draft.parameters.seconds} onChange={(event) => update({ parameters: { ...draft.parameters, seconds: Number(event.target.value) } })} /><strong>{draft.parameters.seconds.toFixed(0)} 秒</strong></div></Field>
          </div>
        </Section>
      </OptionalModuleColumn>

      <OptionalModuleColumn label="音效生成与项目素材">
        <ModuleGenerateCard actions={<Badge tone="neutral">预览</Badge>}>
          <div className={styles.generateBody}>
            <Button className={styles.generateButton} variant="primary" icon={<Sparkles size={17} />} disabled>生成音效</Button>
            <dl className={styles.specs}><div><dt>采样率</dt><dd>48 kHz</dd></div><div><dt>格式</dt><dd>原生 WAV</dd></div><div><dt>声道</dt><dd>保持模型输出</dd></div><div><dt>命名</dt><dd>项目名_音效_序号_时间</dd></div></dl>
            <p>模型与推理接入完成后，生成任务会进入全局串行队列。</p>
          </div>
        </ModuleGenerateCard>
        <ModuleCurrentOutput actions={<Badge tone="neutral">示例预览</Badge>}>
          <div className={styles.previewAsset}><span><AudioLines size={20} /></span><div><strong>雨夜城市街道</strong><small>48 kHz · 原始声道 · 10 秒</small></div></div>
          <div className={styles.fakeWave}>{Array.from({ length: 72 }, (_, index) => <i key={index} style={{ height: `${12 + ((index * 17) % 48)}%` }} />)}</div>
          <div className={styles.lockedActions}><Button variant="secondary" icon={<FolderOpen size={14} />} disabled>打开目录</Button><Button variant="primary" icon={<Download size={14} />} disabled>下载</Button></div>
        </ModuleCurrentOutput>
        <ModuleActivityTimeline><EmptyState title="暂无任务与输出" detail="推理接入后，任务状态和生成结果会统一保存在这里。" /></ModuleActivityTimeline>
      </OptionalModuleColumn>
    </OptionalModuleWorkbench>
  </>;
}
