import { afterEach, expect, it, vi } from 'vitest';
import example from '../../../contracts/check-result.v1.synthetic.json';
import {
  FindingsHttpError,
  InvalidFindingsResponse,
  loadFindings,
} from '../../src/pages/checks/loadFindings';
import { formatLocation } from '../../src/pages/checks/reviewResult';

const id = example.run_id;

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

it('читает результат с меткой синтетики, основаниями, исключениями и точными строками', async () => {
  const fetchMock = stubFetch(Response.json(example.result));
  const signal = new AbortController().signal;
  const findings = await loadFindings(id, signal);

  expect(fetchMock).toHaveBeenCalledWith('/api/v0/runs/synthetic-example/findings', { signal, redirect: 'error' });
  expect(findings).toMatchObject({ runId: id, synthetic: true });
  expect(findings.result.rows[0]).toMatchObject({
    reported_value: '150.50',
    expected_value: '120.50',
    observed_evidence_sum: '120.50',
    unit: 'RUB',
    delta: '30.00',
    status: 'discrepancy',
    calculation: {
      operation: 'sum',
      policy_id: 'demo-sum/1',
      components: [{
        amount: '60.25',
        amount_refs: ['amount-1'],
        contract_refs: ['contract'],
        period_refs: ['period'],
        article_refs: ['article'],
        relation_reason: 'Операция в строке 6 совпала по договору, периоду и статье',
      }, { amount: '60.25', amount_refs: ['amount-2'] }],
    },
  });
  expect(findings.result.rows[1]).toMatchObject({
    reported_value: '0.00',
    expected_value: null,
    delta: null,
    status: 'unverified',
    reasons: [{ code: 'missing_evidence' }],
  });
  expect(findings.result.documents).toEqual(expect.arrayContaining([
    expect.objectContaining({ decision: expect.objectContaining({ state: 'exclude' }) }),
    expect.objectContaining({ errors: [expect.objectContaining({ code: 'unreadable_source' })] }),
  ]));
});

it('сохраняет цепочку от непроверенного показателя до ошибки источника', async () => {
  stubFetch(Response.json(example.result));
  const { result } = await loadFindings(id);

  const row = result.rows.find((item) => item.id === 'row-b');
  expect(row?.root_issue_id).toBe('issue-b');
  const issue = result.summary.primary_issues.find((item) => item.id === row?.root_issue_id);
  expect(issue).toMatchObject({
    code: 'unreadable_source',
    file_error_refs: ['scan-read-error'],
    evidence_refs: [],
  });
  const errors = result.documents.flatMap((document) => document.errors);
  expect(errors.find((error) => error.id === issue?.file_error_refs?.[0])).toMatchObject({
    id: 'scan-read-error',
    code: 'unreadable_source',
  });
  expect(result.summary.primary_issues.find((item) => item.id === 'issue-a')).toMatchObject({
    file_error_refs: [],
    evidence_refs: ['report-a', 'amount-1', 'amount-2'],
  });
});

it('сохраняет наблюдаемую сумму при неполном комплекте и неизвестном ожидаемом значении', async () => {
  const [first, ...otherRows] = example.result.rows;
  const response = {
    ...example.result,
    rows: [{
      ...first,
      observed_evidence_sum: first.calculation.components[0].amount,
      expected_value: null,
      delta: null,
      status: 'unverified',
      completeness: { ...first.completeness, state: 'incomplete', reason: 'Не хватает одной операции', evidence_refs: [] },
      calculation: { ...first.calculation, components: first.calculation.components.slice(0, 1) },
      reasons: [{ code: 'missing_evidence', message: 'Одна операция не подтверждена', evidence_refs: [] }],
      root_issue_id: null,
    }, ...otherRows],
    summary: {
      ...example.result.summary,
      counts: { verified: 0, discrepancy: 0, unverified: 2 },
      primary_issues: example.result.summary.primary_issues.filter((issue) => issue.id !== 'issue-a'),
      conclusion: 'Оба показателя остаются непроверенными.',
    },
  };
  stubFetch(Response.json(response));

  const { result } = await loadFindings(id);
  expect(result.rows[0]).toMatchObject({
    status: 'unverified',
    unit: 'RUB',
    observed_evidence_sum: '60.25',
    expected_value: null,
    delta: null,
    calculation: { components: [{ amount: '60.25', amount_refs: ['amount-1'] }] },
  });
});

it('разбирает все четыре вида адресов и сохраняет различимые фрагменты PDF', async () => {
  const locatorVariants = [
    { kind: 'page', page: 2, line: 7, fragment_id: 'one', bbox: [0.1, 0.2, 0.4, 0.5] },
    { kind: 'sheet', sheet: 'Синтетика', range: 'B2:D4' },
    { kind: 'paragraph', paragraph: 4 },
    { kind: 'table_cell', table: 1, row: 2, cell: 3 },
  ];
  const response = {
    ...example.result,
    evidence: locatorVariants.map((locator, index) => ({
      ...example.result.evidence[index],
      locator,
    })),
  };
  stubFetch(Response.json(response));

  const { result } = await loadFindings(id);
  expect(result.evidence.map(({ locator }) => formatLocation(locator))).toEqual([
    'Страница 2, строка 7, фрагмент one',
    'Лист «Синтетика», B2:D4',
    'Абзац 4',
    'Таблица 1, строка 2, ячейка 3',
  ]);
});

it('передаёт пустые показатели без подстановки фикстуры', async () => {
  stubFetch(Response.json({
    ...example.result,
    rows: [],
    summary: { ...example.result.summary, counts: { verified: 0, discrepancy: 0, unverified: 0 } },
  }));

  const { result } = await loadFindings(id);
  expect(result.rows).toEqual([]);
});

it.each([
  [404, 'run_not_found'],
  [409, 'result_pending'],
  [409, 'run_failed'],
  [503, 'service_unavailable'],
])('сохраняет статус и код отказа %s / %s', async (status, code) => {
  stubFetch(Response.json({ code, message: 'Синтетическая ошибка' }, { status }));
  const promise = loadFindings(id);
  await expect(promise).rejects.toBeInstanceOf(FindingsHttpError);
  await expect(promise).rejects.toMatchObject({ status, code });
});

it('отличает ошибку HTTP прокси от некорректных данных в ответе 200', async () => {
  stubFetch(new Response('Upstream unavailable', { status: 503 }));
  await expect(loadFindings(id)).rejects.toMatchObject({ status: 503, code: undefined });

  stubFetch(new Response('<html>Not JSON</html>'));
  await expect(loadFindings(id)).rejects.toBeInstanceOf(InvalidFindingsResponse);
});

it.each([
  ['иная версия', { ...example.result, schema_version: 'doccheck-check-result/2' }],
  ['другой запуск', { ...example.result, run_id: 'another-run' }],
  ['нет режима данных', { ...example.result, synthetic: null }],
  ['несогласованный статус', { ...example.result, rows: [{ ...example.result.rows[0], status: 'completed' }] }],
  ['числовая сумма', { ...example.result, rows: [{ ...example.result.rows[0], expected_value: 120.50 }] }],
  ['один знак у RUB', { ...example.result, rows: [{ ...example.result.rows[0], expected_value: '120.5' }] }],
  ['адрес без фрагмента', {
    ...example.result,
    evidence: [{ ...example.result.evidence[0], locator: { kind: 'page', page: 1 } }],
  }],
])('отклоняет ответ с нарушением отображаемой части контракта — %s', async (_name, payload) => {
  stubFetch(Response.json(payload));
  await expect(loadFindings(id)).rejects.toBeInstanceOf(InvalidFindingsResponse);
});

it('передаёт сетевую ошибку и отклоняет неподходящий ID до запроса', async () => {
  const networkError = new TypeError('network unavailable');
  const fetchMock = vi.fn().mockRejectedValue(networkError);
  vi.stubGlobal('fetch', fetchMock);

  await expect(loadFindings('..')).rejects.toThrow('Некорректный ID задания.');
  expect(fetchMock).not.toHaveBeenCalled();
  await expect(loadFindings(id)).rejects.toBe(networkError);
});
