import type { ReactNode } from "react";
import styles from "./optionalModuleWorkbench.module.css";

export function OptionalModuleWorkbench({ children, label }: { children: ReactNode; label: string }) {
  return <main className={styles.workspace} aria-label={label}>{children}</main>;
}

export function OptionalModuleColumn({ children, label }: { children: ReactNode; label: string }) {
  return <div className={styles.column} aria-label={label}>{children}</div>;
}
