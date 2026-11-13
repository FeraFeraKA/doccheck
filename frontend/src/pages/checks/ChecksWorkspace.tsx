import { useState } from 'react';
import { NavLink, Outlet } from 'react-router';
import './workspace.css';

export type WorkspaceRole = 'Аспирант' | 'Бухгалтер';

const roles: WorkspaceRole[] = ['Аспирант', 'Бухгалтер'];

export function ChecksWorkspace() {
  const [role, setRole] = useState<WorkspaceRole>('Аспирант');

  return (
    <div className="checks-workspace">
      <aside className="checks-sidebar">
        <NavLink className="checks-brand" to="/checks/new">doccheck</NavLink>
        <nav aria-label="Основная навигация">
          <NavLink to="/checks/new">Новая проверка</NavLink>
          <NavLink to="/checks" end>Обзор проверок</NavLink>
          <NavLink to="/log">Журнал действий</NavLink>
        </nav>
        <div className="checks-role" role="group" aria-label="Роль интерфейса">
          {roles.map((label) => (
            <button type="button" key={label} aria-pressed={role === label} onClick={() => setRole(label)}>
              {label}
            </button>
          ))}
        </div>
      </aside>
      <main className="checks-content">
        <p className="checks-demo">Синтетический режим · файлы остаются в браузере</p>
        <Outlet context={role} />
      </main>
    </div>
  );
}
