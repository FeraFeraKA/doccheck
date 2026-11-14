function renderOrigin(name) {
  const value = process.env[name];
  const url = URL.parse(value ?? '');
  if (!url || url.origin !== value || url.protocol !== 'https:' || !url.hostname.endsWith('.onrender.com')) {
    throw new Error(name + ' must be an https://…onrender.com origin without a path');
  }
  return url.origin;
}

const api = renderOrigin('DOCCHECK_RENDER_ORIGIN');
const uploads = process.env.DOCCHECK_RENDER_UPLOAD_ORIGIN
  ? renderOrigin('DOCCHECK_RENDER_UPLOAD_ORIGIN')
  : null;

export const config = {
  framework: 'vite',
  installCommand: 'npx --yes pnpm@12.14.0 install --frozen-lockfile',
  buildCommand: uploads
    ? 'VITE_DOCCHECK_PUBLIC_DEMO=0 VITE_DOCCHECK_WEB_UPLOADS=1 npx --yes pnpm@12.14.0 build'
    : 'VITE_DOCCHECK_PUBLIC_DEMO=1 npx --yes pnpm@12.14.0 build',
  outputDirectory: 'dist',
  git: { deploymentEnabled: false },
  rewrites: [
    ...(uploads ? [
      { source: '/api/v0/upload-session', destination: uploads + '/api/v0/upload-session' },
      { source: '/api/v0/runs', destination: uploads + '/api/v0/runs' },
      { source: '/api/v0/runs/:path*', destination: uploads + '/api/v0/runs/:path*' },
    ] : []),
    { source: '/health', destination: api + '/health' },
    { source: '/api/:path*', destination: api + '/api/:path*' },
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
