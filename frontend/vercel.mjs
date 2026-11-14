const hostedPreview = process.env.DOCCHECK_HOSTED_PREVIEW === '1';
const value = hostedPreview
  ? process.env.DOCCHECK_PREVIEW_RENDER_ORIGIN
  : process.env.DOCCHECK_RENDER_ORIGIN;
const api = URL.parse(value ?? '');

if (!api || api.origin !== value || api.protocol !== 'https:' || !api.hostname.endsWith('.onrender.com')) {
  throw new Error('Render origin must be an https://…onrender.com origin without a path');
}

const hostedConfig = {
  framework: 'vite',
  installCommand: 'npx --yes pnpm@12.14.0 install --frozen-lockfile',
  buildCommand: 'npx --yes pnpm@12.14.0 exec vite build --config vite.hosted-preview.config.ts',
  outputDirectory: 'dist-hosted-preview',
  git: { deploymentEnabled: false },
  rewrites: [
    { source: '/', destination: '/hosted-preview.html' },
    { source: '/api/preview/v1/:path*', destination: `${api.origin}/api/preview/v1/:path*` },
  ],
  headers: [
    { source: '/api/preview/v1/:path*', headers: [
      { key: 'x-vercel-enable-rewrite-caching', value: '0' },
      { key: 'Cache-Control', value: 'no-store' },
    ] },
  ],
};

const publicConfig = {
  framework: 'vite',
  installCommand: 'npx --yes pnpm@12.14.0 install --frozen-lockfile',
  buildCommand: 'VITE_DOCCHECK_PUBLIC_DEMO=1 npx --yes pnpm@12.14.0 build',
  outputDirectory: 'dist',
  git: { deploymentEnabled: false },
  rewrites: [
    { source: '/health', destination: `${api.origin}/health` },
    { source: '/api/:path*', destination: `${api.origin}/api/:path*` },
    { source: '/checks', destination: '/index.html' },
    { source: '/checks/:path*', destination: '/index.html' },
    { source: '/system-status', destination: '/index.html' },
    { source: '/log', destination: '/index.html' },
  ],
  headers: [
    { source: '/api/:path*', headers: [{ key: 'x-vercel-enable-rewrite-caching', value: '0' }] },
    { source: '/health', headers: [{ key: 'x-vercel-enable-rewrite-caching', value: '0' }] },
  ],
};

export const config = hostedPreview ? hostedConfig : publicConfig;
