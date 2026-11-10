import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

// Vercel serves the UI; a persistent FastAPI host owns identity, data and jobs.
const raw = process.env.HEALTH_HOUSE_BACKEND_URL;
const preview = !raw && process.env.HEALTH_HOUSE_PREVIEW === '1';
if (!raw && !preview) throw new Error('Set HEALTH_HOUSE_BACKEND_URL, or explicitly set HEALTH_HOUSE_PREVIEW=1 for a UI-only preview.');
const backend = raw ? new URL(raw) : null;
if (backend && (backend.protocol !== 'https:' || backend.username || backend.password || backend.search || backend.hash || backend.pathname !== '/')) {
  throw new Error('HEALTH_HOUSE_BACKEND_URL must be an HTTPS origin without credentials, path or query.');
}
const origin = backend?.origin;
const redirect = process.env.HEALTH_HOUSE_REDIRECT === '1';
if (redirect && !backend) throw new Error('HEALTH_HOUSE_REDIRECT requires HEALTH_HOUSE_BACKEND_URL.');
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
if (preview) {
  const file = `${output}/static/static/index.html`;
  const html = (await readFile(file, 'utf8'))
    .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-preview="true">')
    .replace('<div class="workspace-bar">', '<div class="workspace-bar"><p role="status" style="margin-right:auto;font-size:13px;color:#647269">界面预览 · 对话与数据服务尚未连接</p>');
  await writeFile(file, html);
  await writeFile(`${output}/static/backend-unavailable.json`, JSON.stringify({ok:false,error:{code:'backend_not_configured',message:'当前是界面预览，对话与数据服务尚未连接'}}));
}
for (const name of ['index', 'bind', 'care', 'sandbox']) {
  await cp(`${output}/static/static/${name}.html`, `${output}/static/${name}.html`);
}
await mkdir(`${output}/static/admin`, { recursive: true });
await cp(`${output}/static/static/admin`, `${output}/static/admin`, { recursive: true });
await writeFile(`${output}/config.json`, JSON.stringify({
  version: 3,
  routes: redirect ? [
    { src: '/(.*)', status: 307, headers: { Location: `${origin}/$1`, 'Cache-Control': 'no-store' } },
  ] : [
    ...(preview ? [
      { src: '/(?:api(?:/.*)?|health)', dest: '/backend-unavailable.json', status: 503, headers: { 'Cache-Control': 'no-store' } },
    ] : [
      { src: '/api(?:/(.*))?', dest: `${origin}/api/$1`, headers: { 'Cache-Control': 'no-store' } },
      { src: '/health', dest: `${origin}/health`, headers: { 'Cache-Control': 'no-store' } },
    ]),
    { src: '/(bind|care|sandbox)', dest: '/$1.html' },
    { src: '/admin', dest: '/admin/index.html' },
    { handle: 'filesystem' },
    { src: '/', dest: '/index.html' },
  ],
}, null, 2));
console.log(`Built Health House ${token}; mode: ${preview ? 'UI preview (no backend)' : origin}`);
