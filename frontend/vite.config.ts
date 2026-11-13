import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/health': process.env.DOCCHECK_API_TARGET ?? 'http://127.0.0.1:8000',
      '/api': process.env.DOCCHECK_API_TARGET ?? 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.{ts,tsx}', 'tests/integration/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/setup.ts'],
  },
});
