import type { JobStatus, SyntheticJob } from '../../src/pages/home/scaffoldApi';

export const jobId = '12345678-1234-4321-8123-123456789abc';

/** Explicit test double, never returned by the real API or worker. */
export function syntheticJob(status: JobStatus): SyntheticJob {
  return {
    id: jobId,
    synthetic: true,
    status,
    result: status === 'completed' ? { synthetic: true, message: 'Синтетическая проверка завершена.' } : null,
    error: status === 'failed' ? 'synthetic_failure' : null,
    created_at: '2026-11-13T00:00:00Z',
    started_at: status === 'queued' ? null : '2026-11-13T00:00:01Z',
    finished_at: status === 'completed' || status === 'failed' ? '2026-11-13T00:00:02Z' : null,
  };
}
