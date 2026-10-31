// Vercel evaluates this config at deployment time. This origin is public routing
// configuration; provider keys remain exclusively in Railway variables.
const backend = new URL(process.env.FALKRONA_BACKEND_URL || '');
if (backend.protocol !== 'https:' || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash)
  throw new Error('Set FALKRONA_BACKEND_URL to the Railway HTTPS origin, with no path or credentials.');

export default {
  framework: 'vite',
  buildCommand: 'npm run build',
  outputDirectory: 'apps/web/dist',
  installCommand: 'npm ci',
  rewrites: [
    {source: '/api/:path*', destination: `${backend.origin}/api/:path*`},
    {source: '/health/:path*', destination: `${backend.origin}/health/:path*`},
    {source: '/((?!api(?:/|$)|health(?:/|$)|assets/).*)', destination: '/index.html'},
  ],
};
