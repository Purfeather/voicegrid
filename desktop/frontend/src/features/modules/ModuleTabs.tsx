import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { ModuleDescriptor } from "../../types";
import { MODULE_ORDER, MODULE_VISUALS } from "./moduleVisuals";
import styles from "./modules.module.css";

export function ModuleTabs({ modules, beforeNavigate }: { modules: ModuleDescriptor[]; beforeNavigate?: () => Promise<void> }) {
  const { projectId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <nav className={styles.moduleTabs} aria-label="项目制作模块">
      {MODULE_ORDER.map((id) => {
        const { path, fallbackName, icon: Icon } = MODULE_VISUALS[id];
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
            <Icon size={16} />
            <span>{descriptor?.name || fallbackName}</span>
            <i className={descriptor?.installed ? styles.installedDot : styles.optionalDot} />
          </button>
        );
      })}
      <span className={styles.moduleHint}>页签切换不会加载模型</span>
    </nav>
  );
}
