import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.DOCCHECK_HOSTED_BROWSER_URL;
if (!baseURL?.startsWith('https://127.0.0.1:')) {
  throw new Error('DOCCHECK_HOSTED_BROWSER_URL must point to an isolated loopback HTTPS instance');
}

export default defineConfig({
  testDir: './tests/hosted-preview',
  use: { ...devices['Desktop Chrome'], baseURL, ignoreHTTPSErrors: true },
});
