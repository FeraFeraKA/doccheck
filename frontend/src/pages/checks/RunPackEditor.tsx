import { Link, useSearchParams } from 'react-router';
import { getEditableRunPack } from './createRun';
import { RunPackSkeleton } from './CheckLoadingSkeletons';
import { NewCheck } from './NewCheck';
import { useCheckData } from './useCheckData';

export function RunPackEditor() {
  const [params] = useSearchParams();
  const runId = params.get('from');
  if (!runId || import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1') return <NewCheck />;

  return <StoredPack key={runId} runId={runId} />;
}

function StoredPack({ runId }: { runId: string }) {
  const { state, retry } = useCheckData(runId, getEditableRunPack);
  if (state.phase === 'ready') return <NewCheck initialPack={state.data} />;

  return (
    <div className="upload-page">
      <Link to={'/checks/' + encodeURIComponent(runId)}>К результату</Link>
      <h1>Изменить комплект</h1>
      {state.phase === 'loading' ? <RunPackSkeleton /> : (
        <>
          <div className="checks-card">
            <p role="alert">Не удалось получить комплект исходной проверки.</p>
            <button type="button" onClick={retry}>Повторить</button>
          </div>
          <Link to="/checks/new">Новая проверка</Link>
        </>
      )}
    </div>
  );
}
