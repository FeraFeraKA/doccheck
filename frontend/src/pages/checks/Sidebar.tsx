import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { WorkspaceIcon } from './WorkspaceIcon';

const items = [
  { title: 'Новая проверка', url: '/checks/new', icon: 'plus' },
  { title: 'Проверки', url: '/checks', icon: 'clipboard' },
] as const;

export function Sidebar() {
  const { pathname } = useLocation();
  const [choice, setChoice] = useState<boolean | null>(null);
  const [hovered, setHovered] = useState(false);
  const sidebar = useRef<HTMLElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const expanded = choice ?? hovered;
  const isNew = pathname === '/' || pathname === '/checks/new';

  useEffect(() => {
    if (!expanded) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented ||
        (event.target instanceof Element && event.target.closest('dialog:modal, [aria-modal="true"]'))) return;
      setChoice(false);
      if (sidebar.current?.contains(document.activeElement)) toggle.current?.focus();
    }
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [expanded]);

  return (
    <aside ref={sidebar} className="app-sidebar" aria-label="Меню DocCheck" data-expanded={expanded}
      onPointerMove={(event) => {
        // A mount or a layout change can fire pointerenter under a stationary mouse.
        if (!hovered && event.pointerType === 'mouse' &&
          window.matchMedia('(min-width: 701px)').matches) setHovered(true);
      }}
      onPointerLeave={(event) => {
        if (event.pointerType !== 'mouse') return;
        setHovered(false);
        setChoice((previous) => previous === false ? null : previous);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setChoice(null);
      }}>
      <Link to="/checks/new" className="brand" aria-label="DocCheck" onClick={() => setChoice(false)}>
        <span className="brand-symbol"><WorkspaceIcon name="scan" size={23} /></span>
        <span className="brand-name">doccheck<span className="brand-dot" aria-hidden="true" /></span>
      </Link>
      <button ref={toggle} type="button" className="sidebar-toggle" aria-controls="app-sidebar-nav"
        aria-expanded={expanded} aria-label={expanded ? 'Свернуть меню' : 'Развернуть меню'}
        onClick={() => setChoice(!expanded)}><WorkspaceIcon name="menu" /></button>
      <nav id="app-sidebar-nav" aria-label="Основная навигация">
        {items.map(({ title, url, icon }) => {
          const selected = url === '/checks/new' ? isNew : !isNew && pathname.startsWith('/checks');
          return <Link key={url} to={url} className={classes('nav-item', selected && 'active')}
            aria-label={title} aria-current={selected ? 'page' : undefined}
            onFocus={(event) => { if (event.currentTarget.matches(':focus-visible')) setChoice(true); }}
            onClick={() => setChoice(false)}>
            <WorkspaceIcon name={icon} size={19} />
            <span>{title}</span>
          </Link>;
        })}
      </nav>
      <Link className="system-status-link" to="/system-status" aria-label="Проверка системы"
        onFocus={(event) => { if (event.currentTarget.matches(':focus-visible')) setChoice(true); }}>
        <WorkspaceIcon name="status" size={19} /><span>Проверка системы</span>
      </Link>
    </aside>
  );
}
