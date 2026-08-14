import type { SVGProps } from "react";

export function VoiceGridMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 64 64" fill="none" aria-hidden="true" {...props}>
      <rect x="4" y="4" width="56" height="56" rx="14" stroke="currentColor" strokeWidth="4" />
      <path d="M14 30v4m8-10v16m8-23v30m8-25v20m8-14v8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <rect x="44" y="14" width="6" height="6" rx="1" fill="currentColor" />
      <rect x="50" y="22" width="4" height="4" rx="1" fill="currentColor" />
    </svg>
  );
}
