import { AudioLines, MicVocal, Sparkles } from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { ModuleDescriptor, ModuleId } from "../../types";
import styles from "./modules.module.css";

const TABS: Array<{ id: ModuleId; path: string; icon: typeof AudioLines }> = [
  { id: "speech", path: "speech", icon: MicVocal },
  { id: "voice_design", path: "voice-design", icon: Sparkles },
  { id: "sound_effect", path: "sound-effect", icon: AudioLines },
];

export function ModuleTabs({ modules, beforeNavigate }: { modules: ModuleDescriptor[]; beforeNavigate?: () => Promise<void> }) {
  const { projectId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <nav className={styles.moduleTabs} aria-label="项目制作模块">
      {TABS.map(({ id, path, icon: Icon }) => {
        const descriptor = modules.find((item) => item.id === id);
        const active = location.pathname.endsWith(`/${path}`);
        return (
          <button
            key={id}
            className={active ? styles.moduleTabActive : ""}
            onClick={async () => {
              if (active) return;
              try {
                await beforeNavigate?.();
                navigate(`/projects/${projectId}/${path}`);
              } catch {
                // The current editor reports the save failure and remains open.
              }
            }}
          >
            <Icon size={15} />
            <span>{descriptor?.name || (id === "speech" ? "语音合成" : id === "voice_design" ? "音色设计" : "音效生成")}</span>
            {id !== "speech" && <i className={descriptor?.installed ? styles.installedDot : styles.optionalDot} />}
          </button>
        );
      })}
      <span className={styles.moduleHint}>页签切换不会加载模型</span>
    </nav>
  );
}
