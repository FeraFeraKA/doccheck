import type { ReactNode } from 'react';

const icons = {
  scan: <><path d="M4 7V6a2 2 0 0 1 2-2h2m8 0h2a2 2 0 0 1 2 2v1m0 10v1a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-1" /><path d="M7 12h10" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  clipboard: <><rect x="8" y="3" width="8" height="4" rx="1" /><path d="M16 5h2a2 2 0 0 1 2 2v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a2 2 0 0 1 2-2h2m2 6h6m-6 5h6M8 11h.01M8 16h.01" /></>,
  arrow: <path d="M5 12h14m-7-7 7 7-7 7" />,
  check: <path d="m5 12 4 4L19 6" />,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6" /><path d="M12 18v-6m-3 3 3-3 3 3" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
} satisfies Record<string, ReactNode>;

export function WorkspaceIcon({ name, size = 20 }: { name: keyof typeof icons; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {icons[name]}
  </svg>;
}
