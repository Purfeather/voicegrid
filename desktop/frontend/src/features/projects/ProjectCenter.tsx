import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AudioLines, Clock3, FolderOpen, MicVocal, Plus, RotateCcw, Search, Sparkles, Trash2, Waves } from "lucide-react";
import type { ModuleDescriptor, ModuleId, ProjectSummary } from "../../types";
import { Badge, Button, EmptyState, Field, Modal, Select, TextInput } from "../../components/UI";
import styles from "./projectCenter.module.css";

interface Props {
  projects: ProjectSummary[];
  modules: ModuleDescriptor[];
  modulesLoading: boolean;
  modulesError: string;
  loading: boolean;
  error: string;
  startupNotice?: ReactNode;
  onRetry: () => void;
  onCreate: (name: string, language: string) => Promise<void>;
  onOpen: (id: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

const MODULE_OVERVIEW: Array<{ id: ModuleId; label: string; purpose: string; icon: typeof MicVocal }> = [
  { id: "speech", label: "语音合成", purpose: "参考音色、情感与长文本配音", icon: MicVocal },
  { id: "voice_design", label: "音色设计", purpose: "从文字描述创建可复用音色", icon: Sparkles },
  { id: "sound_effect", label: "音效生成", purpose: "从场景描述生成项目音效", icon: AudioLines },
];

function moduleState(module: ModuleDescriptor | undefined, loading: boolean, failed: boolean) {
  if (loading) return { label: "正在检测", tone: "neutral" as const };
  if (failed || !module) return { label: "状态不可用", tone: "neutral" as const };
  if (module.install_state === "installing") return { label: `安装中 ${Math.round(module.install_progress * 100)}%`, tone: "warning" as const };
  if (module.install_state === "repair_required" || module.install_state === "failed") return { label: "需要修复", tone: "warning" as const };
  if (module.installed && module.engine_available) return { label: "已就绪", tone: "success" as const };
  if (module.installed) return { label: "模型已安装", tone: "neutral" as const };
  return { label: "可选安装", tone: "neutral" as const };
}

export function ProjectCenter({ projects, modules, modulesLoading, modulesError, loading, error, startupNotice, onRetry, onCreate, onOpen, onDelete }: Props) {
  const [query, setQuery] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("Chinese");
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [showSkeleton, setShowSkeleton] = useState(false);
  const [showStage, setShowStage] = useState(false);
  useEffect(() => {
    if (!loading) { setShowSkeleton(false); setShowStage(false); return; }
    const skeletonTimer = window.setTimeout(() => setShowSkeleton(true), 300);
    const stageTimer = window.setTimeout(() => setShowStage(true), 1500);
    return () => { window.clearTimeout(skeletonTimer); window.clearTimeout(stageTimer); };
  }, [loading]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized ? projects.filter((project) => project.name.toLocaleLowerCase().includes(normalized)) : projects;
  }, [projects, query]);

  async function create() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await onCreate(name.trim(), language);
      setModalOpen(false);
      setName("");
    } finally {
      setBusy(false);
    }
  }

  async function remove(project: ProjectSummary) {
    const confirmed = window.confirm(`确定删除项目“${project.name}”吗？\n\n项目文件、任务和历史记录将被删除，此操作无法撤销。`);
    if (!confirmed) return;
    setDeletingId(project.id);
    try {
      await onDelete(project.id);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <main id="main-content" className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <span className={styles.kicker}><Waves size={14} /> Local Voice Production</span>
          <h1>把注意力留给表演，<br /><em>其余交给工作台。</em></h1>
          <p>从参考音色与情感设计，到文本切分、批量生成和成品交付，一站完成专业 AI 配音制作。</p>
          <Button variant="primary" icon={<Plus size={17} />} onClick={() => setModalOpen(true)}>新建配音项目</Button>
        </div>
        <div className={styles.heroSystem} aria-label="项目制作模块状态">
          <header className={styles.moduleOverviewHeader}><span>PROJECT MODULES</span><strong>三种制作能力，共享同一项目</strong></header>
          {MODULE_OVERVIEW.map(({ id, label, purpose, icon: Icon }) => {
            const state = moduleState(modules.find((item) => item.id === id), modulesLoading, Boolean(modulesError));
            return <div className={styles.moduleOverviewRow} key={id}>
              <span className={styles.moduleOverviewIcon}><Icon size={17} /></span>
              <span className={styles.moduleOverviewCopy}><strong>{label}</strong><small>{purpose}</small></span>
              <Badge tone={state.tone}>{state.label}</Badge>
            </div>;
          })}
        </div>
      </section>

      <section className={styles.projectsSection} aria-busy={loading}>
        <header>
          <div><span>PROJECTS</span><h2>最近项目</h2></div>
          <div className={styles.search}><Search size={15} /><input aria-label="搜索项目" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目名称" /></div>
        </header>
        {startupNotice && <div className={styles.startupNotice}>{startupNotice}</div>}
        {loading ? (showSkeleton ? <div role="status" aria-live="polite"><span className={styles.srStatus}>{showStage ? "正在读取本地项目索引，请稍候。" : "正在读取项目。"}</span>{showStage && <div className={styles.loadingStage}><Waves size={14} />正在读取本地项目索引</div>}<div className={styles.loadingGrid}>{Array.from({ length: 3 }, (_, index) => <i key={index} />)}</div></div> : <div className={styles.loadingReserve} aria-hidden="true" />) : error ? <EmptyState title="项目列表暂时不可用" detail={error} action={<Button variant="primary" icon={<RotateCcw size={15} />} onClick={onRetry}>重新载入项目</Button>} /> : filtered.length ? (
          <div className={styles.projectGrid}>
            {filtered.map((project) => (
              <article
                key={project.id}
                className={styles.projectCard}
                tabIndex={0}
                onClick={() => { if (deletingId !== project.id) void onOpen(project.id); }}
                onKeyDown={(event) => { if ((event.key === "Enter" || event.key === " ") && deletingId !== project.id) void onOpen(project.id); }}
              >
                <div className={styles.projectAccent} />
                <header><span className={project.recovery_available ? styles.recoveryBadge : ""}><Badge tone={project.recovery_available ? "accent" : "success"}>{project.recovery_available ? "已恢复最近自动保存" : "项目已保存"}</Badge></span><span>{project.output_count} 条输出</span></header>
                <div className={styles.projectBody}><h3>{project.name}</h3><p>当前音色：{project.voice}</p></div>
                <footer>
                  <span><Clock3 size={13} />{new Date(project.updated_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
                  <Button
                    className={styles.deleteProject}
                    variant="ghost"
                    icon={<Trash2 size={15} />}
                    busy={deletingId === project.id}
                    onClick={(event) => { event.stopPropagation(); void remove(project); }}
                  >
                    删除项目
                  </Button>
                </footer>
              </article>
            ))}
            <button className={styles.newCard} onClick={() => setModalOpen(true)}><span><Plus size={20} /></span><strong>新建项目</strong><small>创建一个独立的配音工作区</small></button>
          </div>
        ) : <EmptyState title={query ? "没有匹配的项目" : "还没有配音项目"} detail={query ? "尝试更换搜索关键词。" : "创建第一个项目，开始整理文本、音色与输出。"} action={!query && <Button variant="primary" onClick={() => setModalOpen(true)}>新建项目</Button>} />}
      </section>

      <Modal title="新建配音项目" open={modalOpen} onClose={() => setModalOpen(false)} footer={<><Button variant="ghost" onClick={() => setModalOpen(false)}>取消</Button><Button variant="primary" busy={busy} disabled={!name.trim()} onClick={create}>创建并进入</Button></>}>
        <div className={styles.modalFields}>
          <Field label="项目名称" help="名称会用于项目文件夹和默认输出文件名。"><TextInput autoFocus maxLength={80} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：品牌宣传片旁白" onKeyDown={(event) => event.key === "Enter" && create()} /></Field>
          <Field label="默认语言"><Select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="Chinese">中文</option><option value="English">English</option><option value="Japanese">日本語</option><option value="Korean">한국어</option></Select></Field>
          <div className={styles.localNote}><FolderOpen size={17} /><div><strong>本地独立项目</strong><span>文本、参数和输出记录会自动保存在当前测试版目录内。</span></div></div>
        </div>
      </Modal>
    </main>
  );
}
