// Local static dashboard server. No API proxy, credentials or backend state.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('.', import.meta.url));
const allowed = new Set(['index.html', 'reviewer.css', 'dashboard.mjs', 'api.mjs',
  'controller.mjs', 'fixture.mjs', 'fixtures.json', 'synthetic.jpg']);
const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.mjs': 'text/javascript',
  '.json': 'application/json', '.jpg': 'image/jpeg' };
http.createServer(async (req, res) => {
  try {
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405).end(); return; }
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).slice(1) || 'index.html';
    if (!allowed.has(name)) { res.writeHead(404).end('Not found'); return; }
    const bytes = await readFile(path.join(root, name));
    res.writeHead(200, { 'Content-Type': mime[path.extname(name)], 'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY' });
    res.end(req.method === 'HEAD' ? undefined : bytes);
  } catch { res.writeHead(404).end('Not found'); }
}).listen(8003, '127.0.0.1', () => console.log('Local dashboard: http://127.0.0.1:8003 (fixture mode by default)'));
