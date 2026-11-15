// Fresh Google Play installs/ratings for the apps of a base snapshot (data/snapshots/<base>/gplay.csv).
// Usage: node gplay_refresh.mjs <node_modules_dir> [date=today] [base=earliest snapshot]      (run from the workspace root)
// Writes data/snapshots/<date>/gplay.csv. Cache: <cache root>/gplay_app_<date>/ ($NF_CACHE_DIR or data/cache),
// separate from the S8 app cache so that old cards are not reused.
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';

const nm = process.argv[2];
const require = createRequire(path.join(nm, '/'));
const gplay = require('google-play-scraper').default || require('google-play-scraper');
const ROOT = process.cwd();
const SNAP = path.join(ROOT, 'data', 'snapshots');
const date = process.argv[3] || new Date().toISOString().slice(0, 10);
const base = process.argv[4] || fs.readdirSync(SNAP).filter(d => fs.statSync(path.join(SNAP, d)).isDirectory()).sort()[0];
const cache = path.join(process.env.NF_CACHE_DIR || path.join(ROOT, 'data', 'cache'), `gplay_app_${date}`);
fs.mkdirSync(cache, { recursive: true });
fs.mkdirSync(path.join(SNAP, date), { recursive: true });

function parseCsv(text) {
  const rows = []; let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (c !== '\r') cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [h, ...rest] = rows; return rest.filter(r => r.length === h.length).map(r => Object.fromEntries(h.map((k, i) => [k.replace(/^\uFEFF/, ''), r[i]])));
}
const baseRows = parseCsv(fs.readFileSync(path.join(SNAP, base, 'gplay.csv'), 'utf8'));
const esc = v => '"' + String(v ?? '').replace(/"/g, '""').replace(/\r?\n/g, ' ') + '"';
const rows = ['niche_id,country,appId,title,developer,maxInstalls,ratings,released'];
let n = 0, fetched = 0;
const seen = new Map();   // the same app in several niches is fetched once
for (const m of baseRows) {
  const ck = `${m.country}_${m.appId}`;
  let a = seen.get(ck);
  if (!a) {
    const key = path.join(cache, `${ck}.json`);
    if (fs.existsSync(key)) a = JSON.parse(fs.readFileSync(key, 'utf8'));
    else {
      try {
        const x = await gplay.app({ appId: m.appId, country: m.country, lang: m.country === 'ru' ? 'ru' : 'en' });
        a = { title: x.title, developer: x.developer, maxInstalls: x.maxInstalls, ratings: x.ratings, released: x.released };
        fs.writeFileSync(key, JSON.stringify(a)); fetched++;
        await new Promise(r => setTimeout(r, 700));
      } catch (e) { a = { error: e.message }; console.error('!!', m.appId, e.message.slice(0, 80)); await new Promise(r => setTimeout(r, 3000)); }
    }
    seen.set(ck, a);
  }
  if (a.error) continue;
  rows.push([m.niche_id, m.country, m.appId, a.title, a.developer, a.maxInstalls, a.ratings, a.released].map(esc).join(','));
  if (++n % 50 === 0) console.log(n, '/', baseRows.length, 'fetched', fetched);
}
fs.writeFileSync(path.join(SNAP, date, 'gplay.csv'), rows.join('\n'), 'utf8');
console.log('->', path.join(SNAP, date, 'gplay.csv'), rows.length - 1, 'fetched', fetched);
