import { Link, useLocation } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { WorkspaceIcon } from './WorkspaceIcon';

const items = [
  { title: 'Новая проверка', url: '/checks/new', icon: 'plus' },
  { title: 'Обзор проверок', url: '/checks', icon: 'clipboard' },
] as const;

export function Sidebar() {
  const { pathname } = useLocation();
  const isNew = pathname === '/' || pathname === '/checks/new';
  return (
    <aside className="app-sidebar">
      <Link to="/checks/new" className="brand">
        <span className="brand-symbol"><WorkspaceIcon name="scan" size={23} /></span>
        doccheck
        <span className="brand-dot" aria-hidden="true" />
      </Link>
      <nav aria-label="Основная навигация">
        {items.map(({ title, url, icon }) => {
          const selected = url === '/checks/new' ? isNew : !isNew && pathname.startsWith('/checks');
          return <Link key={url} to={url} className={classes('nav-item', selected && 'active')}
            aria-current={selected ? 'page' : undefined}>
            <WorkspaceIcon name={icon} size={19} />
            <span>{title}</span>
          </Link>;
        })}
      </nav>
      <div className="sidebar-bottom">
        <div className="profile">
          <span className="profile-avatar" aria-hidden="true">Б</span>
          <strong>Бухгалтер</strong>
        </div>
        <Link className="system-status-link" to="/system-status">Проверка системы</Link>
      </div>
    </aside>
  );
}
