import type { ReactNode } from 'react';

const icons = {
  plus: <path d="M12 5v14M5 12h14" />,
  arrowDown: <path d="M12 5v14m-5-5 5 5 5-5" />,
  arrowUpRight: <path d="M7 17 17 7M7 7h10v10" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  alert: <><circle cx="12" cy="12" r="10" /><path d="M12 8v4m0 4h.01" /></>,
  check: <><path d="M22 11.1V12a10 10 0 1 1-5.9-9.1" /><path d="m9 11 3 3L22 4" /></>,
  clipboard: <><rect x="8" y="3" width="8" height="4" rx="1" /><path d="M16 5h2a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m1 7h6m-6 4h6" /></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6" /><circle cx="11" cy="14" r="3" /><path d="m13 16 2 2" /></>,
  files: <><path d="M15 2H6a2 2 0 0 0-2 2v12m12-9H9a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-9Zm0 0v4h4" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  sliders: <><path d="M21 4h-7M10 4H3m18 8h-9m-4 0H3m18 8h-4m-4 0H3M14 2v4m-6 4v4m9 4v4" /></>,
} satisfies Record<string, ReactNode>;

export function OverviewIcon({ name, size = 18 }: { name: keyof typeof icons; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {icons[name]}
    </svg>
  );
}
