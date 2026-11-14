import { defineConfig, devices } from '@playwright/test';

const target = new URL(process.env.DOCCHECK_LIVE_URL ?? 'http://127.0.0.1:8080');
if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' || target.href !== target.origin + '/') {
  throw new Error('Use the HTTP origin of the local DocCheck instance on 127.0.0.1.');
}

export default defineConfig({
  testDir: './tests/live',
  workers: 1,
  timeout: 300_000,
  use: { baseURL: target.origin, ...devices['Desktop Chrome'] },
});
