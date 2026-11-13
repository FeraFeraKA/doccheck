import { Route, Routes } from 'react-router';
import { CheckDetail, CheckLog } from '../pages/checks/CheckDetail';
import { ChecksOverview } from '../pages/checks/ChecksOverview';
import { ChecksWorkspace } from '../pages/checks/ChecksWorkspace';
import { NewCheck } from '../pages/checks/NewCheck';
import { HomePage } from '../pages/home/HomePage';

export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route element={<ChecksWorkspace />}>
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
