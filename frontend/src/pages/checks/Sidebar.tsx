import { Link, useLocation } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { WorkspaceIcon } from './WorkspaceIcon';

const items = [
  { title: 'Новая проверка', url: '/checks/new', icon: 'plus' },
  { title: 'Проверки', url: '/checks', icon: 'clipboard' },
] as const;

export function Sidebar() {
  const { pathname } = useLocation();
  const path = pathname.replace(/\/$/, '');
  const isNew = path === '' || path === '/checks/new';

  return (
    <aside className="app-sidebar" aria-label="Меню DocCheck">
      <Link to="/checks/new" className="brand" aria-label="DocCheck">
        <span className="brand-symbol"><WorkspaceIcon name="scan" size={23} /></span>
        <span className="brand-name">doccheck<span className="brand-dot" aria-hidden="true" /></span>
      </Link>
      <nav aria-label="Основная навигация">
        {items.map(({ title, url, icon }) => {
          const selected = url === '/checks/new' ? isNew : !isNew && (path === '/checks' || path.startsWith('/checks/'));
          return <Link key={url} to={url} className={classes('nav-item', selected && 'active')}
            aria-label={title} aria-current={selected ? 'page' : undefined}>
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
