// Vercel evaluates this config at deployment time. This origin is public routing
// configuration; provider keys remain exclusively in Railway variables.
const invalidOrigin = 'Set FALKRONA_BACKEND_URL to the Railway HTTPS origin, with no path or credentials.';
let backend: URL;
try {
  backend = new URL(process.env.FALKRONA_BACKEND_URL || '');
} catch {
  throw new Error(invalidOrigin);
}
if (backend.protocol !== 'https:' || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash)
  throw new Error(invalidOrigin);

export const config = {
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
