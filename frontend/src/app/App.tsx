import { Route, Routes } from 'react-router';
import { CheckDetail, CheckLog, ChecksOverview, ChecksWorkspace, NewCheck } from '../pages/checks';
import { HomePage } from '../pages/home/HomePage';

export function App() {
  return (
    <Routes>
      <Route path="/system-status" element={<HomePage />} />
      <Route element={<ChecksWorkspace />}>
        <Route index element={<NewCheck />} />
        <Route path="/checks" element={<ChecksOverview />} />
        <Route path="/checks/new" element={<NewCheck />} />
        <Route path="/checks/:id" element={<CheckDetail view="table" />} />
        <Route path="/checks/:id/documents" element={<CheckDetail view="documents" />} />
        <Route path="/checks/:id/exceptions" element={<CheckDetail view="exceptions" />} />
        <Route path="/checks/:id/conclusion" element={<CheckDetail view="conclusion" />} />
        <Route path="/checks/:id/log" element={<CheckDetail view="log" />} />
        <Route path="/log" element={<CheckLog />} />
      </Route>
    </Routes>
  );
}
