// Google Play app cards for the apps in gplay_match.csv: installs (maxInstalls), ratings, release date, price/IAP.
// Usage: node gplay_details.mjs <node_modules_dir> [shard/total]      (run from the workspace root)
//   shard/total (e.g. 1/3) processes every total-th row, so several processes can fetch in parallel;
//   a final run without a shard assembles the CSV from the cache.
// Reads data/out/gplay_match.csv, writes data/out/gplay_apps.csv.
// Cache: <cache root>/gplay_app/<country>_<appId>.json ($NF_CACHE_DIR or data/cache).
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const nm = process.argv[2];
const require = createRequire(path.join(nm, '/'));
// google-play-scraper 10 is ESM-only and require() of an ES module needs Node 20.19+: resolve it in node_modules, load with import()
const gplay = (await import(pathToFileURL(require.resolve('google-play-scraper')).href)).default;
const ROOT = process.cwd();
const cache = path.join(process.env.NF_CACHE_DIR || path.join(ROOT, 'data', 'cache'), 'gplay_app');
fs.mkdirSync(cache, { recursive: true });

function parseCsv(text) {   // minimal CSV parser (quotes, commas, newlines inside quotes)
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
const all = parseCsv(fs.readFileSync(path.join(ROOT, 'data', 'out', 'gplay_match.csv'), 'utf8'));
const [shard, total] = (process.argv[3] || '0/1').split('/').map(Number);
const match = all.filter((_, i) => i % total === shard);
const esc = v => '"' + String(v ?? '').replace(/"/g, '""').replace(/\r?\n/g, ' ') + '"';
const rows = ['niche_id,country,appId,title,developer,installs,maxInstalls,ratings,reviews,score,released,updated,free,priceText,offersIAP,IAPRange,genre,hits,best_pos'];
let n = 0, fetched = 0;
for (const m of match) {
  const key = path.join(cache, `${m.country}_${m.appId}.json`);
  let a;
  if (fs.existsSync(key)) a = JSON.parse(fs.readFileSync(key, 'utf8'));
  else {
    try {
      a = await gplay.app({ appId: m.appId, country: m.country, lang: m.country === 'ru' ? 'ru' : 'en' });
      a = { title: a.title, developer: a.developer, installs: a.installs, maxInstalls: a.maxInstalls, ratings: a.ratings, reviews: a.reviews, score: a.score,
            released: a.released, updated: a.updated, free: a.free, priceText: a.priceText, offersIAP: a.offersIAP, IAPRange: a.IAPRange, genre: a.genre };
      fs.writeFileSync(key, JSON.stringify(a)); fetched++;
      await new Promise(r => setTimeout(r, 700));
    } catch (e) { a = { error: e.message }; console.error('!!', m.appId, e.message.slice(0, 80)); await new Promise(r => setTimeout(r, 3000)); }   // errors are not cached
  }
  if (a.error) continue;
  rows.push([m.niche_id, m.country, m.appId, a.title, a.developer, a.installs, a.maxInstalls, a.ratings, a.reviews, a.score, a.released,
             a.updated ? new Date(a.updated).toISOString().slice(0, 10) : '', a.free, a.priceText, a.offersIAP, a.IAPRange, a.genre, m.hits, m.best_pos].map(esc).join(','));
  if (++n % 50 === 0) console.log(n, '/', match.length, 'fetched', fetched);
}
fs.writeFileSync(path.join(ROOT, 'data', 'out', 'gplay_apps.csv'), '\uFEFF' + rows.join('\n'), 'utf8');
if (total === 1) console.log('-> gplay_apps.csv', rows.length - 1); else console.log('shard done', shard, '/', total, 'fetched', fetched);
