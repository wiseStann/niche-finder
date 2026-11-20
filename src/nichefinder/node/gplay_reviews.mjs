// Newest Russian Google Play reviews for the apps in data/out/ru_reviews_gplay_plan.json ([{appId, num}]).
// Usage: node gplay_reviews.mjs <node_modules_dir> <YYYY-MM>      (run from the workspace root)
//   The run month is part of the cache key: a re-run in the same month reads the cache, the next month fetches again.
// Cache: <cache root>/gplay_reviews/ru_<appId>_<YYYY-MM>.json ($NF_CACHE_DIR or data/cache); errors are not cached.
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const nm = process.argv[2];
const month = process.argv[3];
if (!/^\d{4}-\d{2}$/.test(month || '')) { console.error('usage: gplay_reviews.mjs <node_modules_dir> <YYYY-MM>'); process.exit(2); }
const require = createRequire(path.join(nm, '/'));
// google-play-scraper 10 is ESM-only: resolve it in node_modules, load with import() (see gplay_details.mjs)
const gplay = (await import(pathToFileURL(require.resolve('google-play-scraper')).href)).default;
const ROOT = process.cwd();
const cache = path.join(process.env.NF_CACHE_DIR || path.join(ROOT, 'data', 'cache'), 'gplay_reviews');
fs.mkdirSync(cache, { recursive: true });
const plan = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'out', 'ru_reviews_gplay_plan.json'), 'utf8'));
let fetched = 0, cached = 0, failed = 0;
for (const { appId, num } of plan) {
  const key = path.join(cache, `ru_${appId}_${month}.json`);
  if (fs.existsSync(key)) { cached++; continue; }
  try {
    const r = await gplay.reviews({ appId, lang: 'ru', country: 'ru', sort: gplay.sort.NEWEST, num });
    const reviews = (r.data ?? r).map(x => ({ id: x.id, date: x.date, score: x.score, title: x.title, text: x.text,
                                              version: x.version, thumbsUp: x.thumbsUp }));
    fs.writeFileSync(key, JSON.stringify({ appId, month, reviews }));
    fetched++;
    console.log(`  ${appId}: ${reviews.length} reviews`);
    await new Promise(res => setTimeout(res, 1000));
  } catch (e) {
    failed++;
    console.error('!!', appId, String(e.message || e).slice(0, 80));
    await new Promise(res => setTimeout(res, 3000));
  }
}
console.log(`gplay reviews: fetched ${fetched}, cached ${cached}, failed ${failed}`);
