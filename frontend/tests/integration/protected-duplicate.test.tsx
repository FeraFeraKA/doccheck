import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import example from '../../../contracts/check-result.v1.synthetic.json';
import { CheckDetail } from '../../src/pages/checks';
import type { RunDetails } from '../../src/pages/checks/checkData';

afterEach(() => vi.unstubAllGlobals());

it('показывает ошибку чтения исключённой защищённой копии', async () => {
  const runId = '123e4567-e89b-42d3-a456-426614174000';
  const message = 'PDF защищён паролем. Загрузите доступную копию файла.';
  const representative = {
    id: 'protected-original',
    name: 'protected-a.pdf',
    sha256: 'a'.repeat(64),
    format: 'pdf',
    role: 'support',
    parse_status: 'error',
    decision: { state: 'parse_error', reason_code: 'encrypted_pdf', message, evidence_refs: [] },
    errors: [{ id: 'protected-original-error', code: 'encrypted_pdf', message }],
    duplicate_of: null,
  };
  const duplicate = {
    ...representative,
    id: 'protected-copy',
    name: 'protected-b.pdf',
    duplicate_of: representative.id,
    decision: {
      state: 'exclude', reason_code: 'byte_duplicate',
      message: 'Байты совпадают с другим экземпляром.', evidence_refs: [],
    },
    errors: [{ id: 'protected-copy-error', code: 'encrypted_pdf', message }],
  };
  const result = {
    ...example.result,
    run_id: runId,
    documents: [...example.result.documents, representative, duplicate],
  };
  vi.stubGlobal('matchMedia', () => ({ matches: false }));
  const fetchMock = vi.fn().mockResolvedValue(Response.json(result));
  vi.stubGlobal('fetch', fetchMock);
  const loadRun = async (): Promise<RunDetails> => ({
    title: 'Проверка', status: 'completed_with_issues', result: null,
  });

  render(<MemoryRouter initialEntries={[`/checks/${runId}/documents`]}>
    <Routes><Route path="/checks/:id/documents" element={<CheckDetail view="documents" loadRun={loadRun} />} /></Routes>
  </MemoryRouter>);

  const table = await screen.findByRole('region', { name: 'Таблица документов' });
  const row = within(table).getByRole('button', { name: 'protected-b.pdf' }).closest('tr');
  if (!row) throw new Error('Строка защищённой копии отсутствует');
  expect(within(row).getByText('Не удалось прочитать')).toBeVisible();
  expect(within(row).getByText('Исключён')).toBeVisible();
  expect(within(row).getByText(message)).toBeVisible();
  expect(within(row).queryByText('Основание')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /^Исключены \(/ }));
  expect(within(table).getByRole('button', { name: 'protected-b.pdf' })).toBeVisible();
  expect(fetchMock).toHaveBeenCalledWith(`/api/v0/runs/${runId}/findings`, expect.anything());
});
