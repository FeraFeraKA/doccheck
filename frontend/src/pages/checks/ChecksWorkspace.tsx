import { useLayoutEffect } from 'react';
import { Outlet, useLocation, useNavigationType } from 'react-router';
import { Sidebar } from './Sidebar';
import './workspace.css';
import './accountant-workspace.css';

export function ChecksWorkspace() {
  const { pathname } = useLocation();
  const navigationType = useNavigationType();

  useLayoutEffect(() => {
    if (navigationType !== 'POP') window.scrollTo(0, 0);
  }, [navigationType, pathname]);

  return (
    <div className="checks-workspace accountant-workspace">
      <Sidebar />
      <div className="app-content">
        <main className="app-main checks-content">
          <div className="page-content">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
