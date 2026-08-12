import type { SVGProps } from "react";

export function VoiceGridMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 64 64" fill="none" aria-hidden="true" {...props}>
      <rect x="5" y="5" width="54" height="54" rx="13" stroke="currentColor" strokeWidth="4" />
      <path d="M15 29v6m8-11v16m8-23v30m8-24v18m8-13v8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <rect x="45" y="15" width="6" height="6" rx="1" fill="currentColor" />
      <rect x="49" y="23" width="5" height="5" rx="1" fill="currentColor" />
    </svg>
  );
}
