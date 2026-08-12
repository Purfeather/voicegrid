import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { LoaderCircle, X } from "lucide-react";
import styles from "./ui.module.css";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  busy?: boolean;
  icon?: ReactNode;
};

export function Button({ variant = "secondary", busy, icon, children, className = "", ...props }: ButtonProps) {
  return (
    <button className={`${styles.button} ${styles[variant]} ${className}`} disabled={busy || props.disabled} {...props}>
      {busy ? <LoaderCircle className={styles.spin} size={16} aria-hidden="true" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({ label, children, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return <button className={`${styles.iconButton} ${className}`} aria-label={label} title={label} {...props}>{children}</button>;
}

export function Section({ title, eyebrow, actions, children, className = "" }: HTMLAttributes<HTMLElement> & { title: string; eyebrow?: string; actions?: ReactNode }) {
  return (
    <section className={`${styles.section} ${className}`}>
      <header className={styles.sectionHeader}>
        <div>{eyebrow && <span className={styles.eyebrow}>{eyebrow}</span>}<h2>{title}</h2></div>
        {actions && <div className={styles.actions}>{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Field({ label, help, children, compact = false }: { label: string; help?: string; children: ReactNode; compact?: boolean }) {
  return <label className={`${styles.field} ${compact ? styles.compact : ""}`}><span>{label}</span>{children}{help && <small>{help}</small>}</label>;
}

export function TextInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${styles.input} ${className}`} {...props} />;
}

export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`${styles.input} ${className}`} {...props} />;
}

export function TextArea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${styles.textarea} ${className}`} {...props} />;
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "success" | "warning" | "danger" | "accent"; children: ReactNode }) {
  return <span className={`${styles.badge} ${styles[`badge_${tone}`]}`}>{children}</span>;
}

export function Progress({ value, label }: { value: number; label: string }) {
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return <div className={styles.progress} aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} role="progressbar"><i style={{ width: `${percent}%` }} /></div>;
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <div className={styles.empty}><strong>{title}</strong><span>{detail}</span>{action}</div>;
}

export function Modal({ title, open, onClose, children, footer }: { title: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  if (!open) return null;
  return (
    <div className={styles.modalScrim} role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <header><h2 id="modal-title">{title}</h2><IconButton label="关闭" onClick={onClose}><X size={18} /></IconButton></header>
        <div className={styles.modalBody}>{children}</div>
        {footer && <footer>{footer}</footer>}
      </section>
    </div>
  );
}
