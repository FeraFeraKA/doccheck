import { useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import './source-drawer.css';

function visibleFragment(viewport: HTMLElement) {
  const fragment = viewport.querySelector('.source-viewer-highlight');
  if (!fragment) return null;
  const mark = fragment.getBoundingClientRect();
  const { top, left } = viewport.getBoundingClientRect();
  return mark.width > 0 && mark.height > 0
    && mark.left >= left - 1 && mark.right <= left + viewport.clientWidth + 1
    && mark.top >= top - 1 && mark.bottom <= top + viewport.clientHeight + 1
    ? fragment : null;
}

export function SourceDrawer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const drawer = useRef<HTMLDialogElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const pendingScroll = useRef<{ viewport: HTMLElement; x: number; y: number; fragment: Element | null } | null>(null);
  const fullscreenLabel = fullscreen
    ? 'Свернуть источник в боковую панель'
    : 'Развернуть источник на весь экран';

  useLayoutEffect(() => {
    const dialog = drawer.current;
    if (!dialog) return;
    const trigger = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, []);

  function toggleFullscreen() {
    const viewport = drawer.current?.querySelector<HTMLElement>('.source-viewer-viewport');
    if (viewport) {
      const maxX = viewport.scrollWidth - viewport.clientWidth;
      const maxY = viewport.scrollHeight - viewport.clientHeight;
      pendingScroll.current = {
        viewport,
        x: viewport.scrollLeft / Math.max(1, maxX),
        y: viewport.scrollTop / Math.max(1, maxY),
        fragment: visibleFragment(viewport),
      };
    }
    setFullscreen((value) => !value);
  }

  useLayoutEffect(() => {
    const position = pendingScroll.current;
    pendingScroll.current = null;
    if (!position?.viewport.isConnected) return;
    const { viewport, x, y, fragment } = position;
    viewport.scrollLeft = x * (viewport.scrollWidth - viewport.clientWidth);
    viewport.scrollTop = y * (viewport.scrollHeight - viewport.clientHeight);
    // Preserve a visible selection without overriding a deliberate scroll away.
    if (!fragment?.isConnected || visibleFragment(viewport)) return;
    const bounds = viewport.getBoundingClientRect();
    const mark = fragment.getBoundingClientRect();
    if (mark.left < bounds.left - 1 || mark.right > bounds.left + viewport.clientWidth + 1) {
      viewport.scrollLeft += mark.left + (mark.width - viewport.clientWidth) / 2 - bounds.left;
    }
    if (mark.top < bounds.top - 1 || mark.bottom > bounds.top + viewport.clientHeight + 1) {
      viewport.scrollTop += mark.top + (mark.height - viewport.clientHeight) / 2 - bounds.top;
    }
  }, [fullscreen]);

  return <dialog ref={drawer} className="source-drawer" aria-labelledby="source-drawer-title" data-fullscreen={fullscreen}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect();
      if (event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom) onClose();
    }}>
    <div className="source-drawer-panel">
      <header className="source-drawer-header">
        <h2 id="source-drawer-title">Источник документа</h2>
        <div className="source-drawer-actions">
          <button className="source-drawer-size" type="button" aria-label={fullscreenLabel}
            title={fullscreenLabel} aria-pressed={fullscreen} onClick={toggleFullscreen}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d={fullscreen
                ? 'M8 3v5H3m13-5v5h5M8 21v-5H3m13 5v-5h5'
                : 'M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3'} />
            </svg>
            <span>{fullscreen ? 'Свернуть' : 'На весь экран'}</span>
          </button>
          <button type="button" aria-label="Вернуться к таблице" onClick={onClose}>К таблице</button>
          <button className="source-drawer-close" type="button" aria-label="Закрыть просмотр источника" onClick={onClose}>×</button>
        </div>
      </header>
      <div className="source-drawer-content">{children}</div>
    </div>
  </dialog>;
}
