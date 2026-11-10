import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

// Vercel serves the UI; a persistent FastAPI host owns identity, data and jobs.
const raw = process.env.HEALTH_HOUSE_BACKEND_URL;
if (!raw) throw new Error('Set HEALTH_HOUSE_BACKEND_URL to the persistent FastAPI backend HTTPS origin before deploying.');
const backend = new URL(raw);
if (backend.protocol !== 'https:' || backend.username || backend.password || backend.search || backend.hash || backend.pathname !== '/') {
  throw new Error('HEALTH_HOUSE_BACKEND_URL must be an HTTPS origin without credentials, path or query.');
}
const origin = backend.origin;
const output = '.vercel/output';
await rm(output, { recursive: true, force: true });
await mkdir(`${output}/static`, { recursive: true });
await cp('static', `${output}/static/static`, { recursive: true });
const version = (await readFile('VERSION', 'utf8')).trim();
const revision = process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 8) || 'local';
const token = `${version}-${revision}`;
async function stamp(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const name = path.join(directory, entry.name);
    if (entry.isDirectory()) await stamp(name);
    else if (/\.(html|js|css|svg)$/.test(name)) {
      await writeFile(name, (await readFile(name, 'utf8')).replaceAll('__APP_VERSION__', token));
    }
  }
}
await stamp(`${output}/static/static`);
for (const name of ['index', 'bind', 'care', 'sandbox']) {
  await cp(`${output}/static/static/${name}.html`, `${output}/static/${name}.html`);
}
await mkdir(`${output}/static/admin`, { recursive: true });
await cp(`${output}/static/static/admin/index.html`, `${output}/static/admin/index.html`);
await writeFile(`${output}/config.json`, JSON.stringify({
  version: 3,
  routes: [
    { src: '/api(?:/(.*))?', dest: `${origin}/api/$1`, headers: { 'Cache-Control': 'no-store' } },
    { src: '/health', dest: `${origin}/health`, headers: { 'Cache-Control': 'no-store' } },
    { src: '/(bind|care|sandbox)', dest: '/$1.html' },
    { src: '/admin', dest: '/admin/index.html' },
    { handle: 'filesystem' },
    { src: '/', dest: '/index.html' },
  ],
}, null, 2));
console.log(`Built Health House ${token}; API proxy: ${origin}`);
