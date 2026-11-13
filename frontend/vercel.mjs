const value = process.env.DOCCHECK_RENDER_ORIGIN;
const api = URL.parse(value ?? '');

if (!api || api.origin !== value || api.protocol !== 'https:' || !api.hostname.endsWith('.onrender.com')) {
  throw new Error('DOCCHECK_RENDER_ORIGIN must be an https://…onrender.com origin without a path');
}

export const config = {
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
    { source: '/log', destination: '/index.html' },
  ],
  headers: [
    { source: '/api/:path*', headers: [{ key: 'x-vercel-enable-rewrite-caching', value: '0' }] },
    { source: '/health', headers: [{ key: 'x-vercel-enable-rewrite-caching', value: '0' }] },
  ],
};
