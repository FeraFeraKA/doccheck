import type { ReactNode } from 'react';

const icons = {
  scan: <><path d="M4 7V6a2 2 0 0 1 2-2h2m8 0h2a2 2 0 0 1 2 2v1m0 10v1a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-1" /><path d="M7 12h10" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  pencil: <path d="m14 6 4 4M4 20l4-.9L20 7a2.8 2.8 0 0 0-4-4L4.9 15Z" />,
  minus: <path d="M5 12h14" />,
  download: <path d="M12 3v12m-5-5 5 5 5-5M5 16v4h14v-4" />,
  reset: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></>,
  archive: <><rect x="3" y="4" width="18" height="5" rx="1" /><path d="M5 9v11h14V9m-9 4h4" /></>,
  clipboard: <><rect x="8" y="3" width="8" height="4" rx="1" /><path d="M16 5h2a2 2 0 0 1 2 2v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a2 2 0 0 1 2-2h2m2 6h6m-6 5h6M8 11h.01M8 16h.01" /></>,
  arrow: <path d="M5 12h14m-7-7 7 7-7 7" />,
  check: <path d="m5 12 4 4L19 6" />,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6" /><path d="M12 18v-6m-3 3 3-3 3 3" /></>,
  search: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></>,
  chevron: <path d="m9 18 6-6-6-6" />,
  eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z" /><circle cx="12" cy="12" r="2.5" /></>,
  eyeOff: <path d="M3 3l18 18M10 6.2a10.8 10.8 0 0 1 2-.2c6.5 0 10 6 10 6a15.4 15.4 0 0 1-3.1 3.5M6.4 7.4A15.4 15.4 0 0 0 2 12s3.5 6 10 6c1.6 0 3.1-.4 4.5-1.1" />,
  warning: <path d="M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.5L13.7 3.9a2 2 0 0 0-3.4 0ZM12 9v4m0 3h.01" />,
  help: <><circle cx="12" cy="12" r="10" /><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3m.1 4h.01" /></>,
  fileSearch: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6m-8 8 3 3" /><circle cx="10" cy="13" r="3" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
} satisfies Record<string, ReactNode>;

export function WorkspaceIcon({ name, size = 20 }: { name: keyof typeof icons; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {icons[name]}
  </svg>;
}
