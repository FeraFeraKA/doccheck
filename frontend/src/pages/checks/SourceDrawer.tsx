import { useLayoutEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import './source-drawer.css';

export function SourceDrawer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const drawer = useRef<HTMLDialogElement>(null);

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

  return <dialog ref={drawer} className="source-drawer" aria-labelledby="source-drawer-title"
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
          <button type="button" aria-label="Вернуться к таблице" onClick={onClose}>К таблице</button>
          <button className="source-drawer-close" type="button" aria-label="Закрыть просмотр источника" onClick={onClose}>×</button>
        </div>
      </header>
      <div className="source-drawer-content">{children}</div>
    </div>
  </dialog>;
}
