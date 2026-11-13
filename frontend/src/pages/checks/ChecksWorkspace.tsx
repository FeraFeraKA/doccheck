import { NavLink, Outlet } from 'react-router';
import './workspace.css';

export function ChecksWorkspace() {

  return (
    <div className="checks-workspace">
      <aside className="checks-sidebar">
        <NavLink className="checks-brand" to="/checks/new">doccheck</NavLink>
        <nav aria-label="Основная навигация">
          <NavLink to="/checks/new">Новая проверка</NavLink>
          <NavLink to="/checks" end>Обзор проверок</NavLink>
          <NavLink to="/log">Журнал действий</NavLink>
        </nav>
      </aside>
      <main className="checks-content">
        <Outlet />
      </main>
    </div>
  );
}
