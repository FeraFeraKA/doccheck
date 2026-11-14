import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { WorkspaceIcon } from './WorkspaceIcon';

const items = [
  { title: 'Новая проверка', url: '/checks/new', icon: 'plus' },
  { title: 'Проверки', url: '/checks', icon: 'clipboard' },
  { title: 'Архив проверок', url: '/archive', icon: 'archive' },
] as const;

export function Sidebar() {
  const { pathname } = useLocation();
  const sidebar = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [keyboardExpanded, setKeyboardExpanded] = useState(false);
  const [hoverDismissed, setHoverDismissed] = useState(false);
  const expanded = open || keyboardExpanded || (hovered && !hoverDismissed);
  const path = pathname.replace(/\/$/, '');
  const isNew = path === '' || path === '/checks/new';

  useEffect(() => {
    if (!expanded) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented ||
        (event.target instanceof Element && event.target.closest('dialog:modal, [aria-modal="true"]'))) return;
      const active = document.activeElement;
      if (sidebar.current?.contains(active) && trigger.current?.getClientRects().length) {
        trigger.current.focus();
      }
      setOpen(false);
      setKeyboardExpanded(false);
      setHoverDismissed(true);
    }
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [expanded]);

  const mark = <>
    <span className="brand-symbol"><WorkspaceIcon name="scan" size={23} /></span>
    <span className="brand-name">doccheck<span className="brand-dot" aria-hidden="true" /></span>
  </>;

  return (
    <aside ref={sidebar} className="app-sidebar" aria-label="Меню DocCheck" data-expanded={expanded} data-mobile-open={open}
      onPointerMove={(event) => {
        if (event.pointerType === 'mouse' &&
          window.matchMedia('(min-width: 701px) and (hover: hover)').matches) setHovered(true);
      }}
      onPointerLeave={(event) => {
        if (event.pointerType !== 'mouse') return;
        setHovered(false);
        setHoverDismissed(false);
      }}
      onFocusCapture={(event) => {
        if (event.target !== trigger.current && event.target.matches(':focus-visible') &&
          window.matchMedia('(min-width: 701px)').matches) setKeyboardExpanded(true);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setKeyboardExpanded(false);
      }}>
      <Link to="/checks/new" className="brand" aria-label="DocCheck">{mark}</Link>
      <button ref={trigger} type="button" className="brand sidebar-mobile-trigger" aria-label="Меню разделов"
        aria-expanded={open} aria-controls="doccheck-navigation" onClick={() => {
          setKeyboardExpanded(false);
          setOpen((previous) => !previous);
        }}>{mark}</button>
      <nav id="doccheck-navigation" aria-label="Основная навигация">
        {items.filter(({ url }) => url !== '/archive' || import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO !== '1').map(({ title, url, icon }) => {
          const selected = url === '/archive' ? path === url : url === '/checks/new' ? isNew : !isNew && (path === '/checks' || path.startsWith('/checks/'));
          return <Link key={url} to={url} className={classes('nav-item', selected && 'active')}
            aria-label={title} aria-current={selected ? 'page' : undefined}
            onClick={() => {
              if (open && window.matchMedia('(max-width: 700px)').matches) {
                trigger.current?.focus({ preventScroll: true });
              }
              setOpen(false);
            }}>
            <WorkspaceIcon name={icon} size={19} />
            <span>{title}</span>
          </Link>;
        })}
      </nav>
      <Link className="system-status-link" to="/system-status" aria-label="Проверка системы">
        <WorkspaceIcon name="status" size={19} /><span>Проверка системы</span>
      </Link>
    </aside>
  );
}
