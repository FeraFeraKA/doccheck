import { Link, Outlet } from 'react-router';
import { Sidebar } from './Sidebar';
import './workspace.css';
import './accountant-workspace.css';

export function ChecksWorkspace() {
  return (
    <div className="checks-workspace accountant-workspace">
      <Sidebar />
      <div className="app-content">
        <main className="app-main checks-content">
          <div className="page-content">
            <Outlet />
            <Link className="mobile-system-status-link" to="/system-status">Проверка системы</Link>
          </div>
        </main>
      </div>
    </div>
  );
}
