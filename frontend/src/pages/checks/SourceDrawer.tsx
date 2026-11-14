import { useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import './source-drawer.css';

export function SourceDrawer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const drawer = useRef<HTMLDialogElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const pendingScroll = useRef<{ viewport: HTMLElement; x: number | null; y: number | null } | null>(null);
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
        x: maxX > 0 ? viewport.scrollLeft / maxX : null,
        y: maxY > 0 ? viewport.scrollTop / maxY : null,
      };
    }
    setFullscreen((value) => !value);
  }

  useLayoutEffect(() => {
    const position = pendingScroll.current;
    pendingScroll.current = null;
    if (!position?.viewport.isConnected) return;
    const { viewport, x, y } = position;
    const maxX = viewport.scrollWidth - viewport.clientWidth;
    const maxY = viewport.scrollHeight - viewport.clientHeight;
    if (x !== null) viewport.scrollLeft = x * maxX;
    if (y !== null) viewport.scrollTop = y * maxY;
    if ((x !== null || maxX <= 0) && (y !== null || maxY <= 0)) return;

    // When an axis did not scroll before the resize, there is no scroll ratio
    // to restore. Keep the selected fragment visible if that axis now scrolls.
    const fragment = viewport.querySelector('.source-viewer-highlight');
    if (!fragment) return;
    const bounds = viewport.getBoundingClientRect();
    const mark = fragment.getBoundingClientRect();
    if (x === null && maxX > 0) {
      viewport.scrollLeft += mark.left + (mark.width - viewport.clientWidth) / 2 - bounds.left;
    }
    if (y === null && maxY > 0) {
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
