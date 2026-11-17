// Google Play search for the category queries of every shortlisted niche (like the iTunes Search in S5).
// Usage: node gplay_search.mjs <node_modules_dir>      (run from the workspace root)
// Reads data/out/gplay_search_plan.json: [{niche_id, country, lang, queries: [...]}]
// Writes data/out/gplay_search.csv. Cache: <cache root>/gplay_search/ ($NF_CACHE_DIR or data/cache).
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const nm = process.argv[2];
const require = createRequire(path.join(nm, '/'));
// google-play-scraper 10 is ESM-only and require() of an ES module needs Node 20.19+: resolve it in node_modules, load with import()
const gplay = (await import(pathToFileURL(require.resolve('google-play-scraper')).href)).default;
const ROOT = process.cwd();
const cache = path.join(process.env.NF_CACHE_DIR || path.join(ROOT, 'data', 'cache'), 'gplay_search');
fs.mkdirSync(cache, { recursive: true });
const MAX_Q = 4, NUM = 50;

const plan = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'out', 'gplay_search_plan.json'), 'utf8'));
const esc = v => '"' + String(v ?? '').replace(/"/g, '""').replace(/\r?\n/g, ' ') + '"';
const rows = ['niche_id,country,query,pos,appId,title,developer,score,priceText,free,summary'];
for (const p of plan) {
  for (const q of p.queries.slice(0, MAX_Q)) {
    const key = path.join(cache, `${p.country}__${q.replace(/[^\p{L}\p{N}]+/gu, '_')}.json`);
    let list;
    if (fs.existsSync(key)) list = JSON.parse(fs.readFileSync(key, 'utf8'));
    else {
      try {
        list = await gplay.search({ term: q, num: NUM, country: p.country, lang: p.lang, fullDetail: false });
        fs.writeFileSync(key, JSON.stringify(list));
        await new Promise(r => setTimeout(r, 1200));
      } catch (e) { console.error('!!', p.niche_id, p.country, q, e.message); await new Promise(r => setTimeout(r, 5000)); continue; }
    }
    list.forEach((a, i) => rows.push([p.niche_id, p.country, q, i + 1, a.appId, a.title, a.developer, a.scoreText, a.priceText, a.free, (a.summary || '').slice(0, 200)].map(esc).join(',')));
  }
  console.log(p.niche_id, p.country, rows.length);
}
fs.writeFileSync(path.join(ROOT, 'data', 'out', 'gplay_search.csv'), '\uFEFF' + rows.join('\n'), 'utf8');
console.log('-> gplay_search.csv', rows.length - 1);
