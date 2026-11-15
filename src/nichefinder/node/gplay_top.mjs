// Google Play top charts via google-play-scraper: all non-game categories x {US grossing, RU grossing, RU free}.
// Note: Google Play payments have been blocked in Russia since 2022, so RU top-grossing reflects users with foreign
// cards; RU top-free reflects usage.
// Run: node gplay_top.mjs <node_modules_dir>   (cwd = workspace)  ->  data/raw/gplay_top.csv
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';

const nm = process.argv[2];
const require = createRequire(path.join(nm, '/'));
const gplay = require('google-play-scraper').default || require('google-play-scraper');
const cacheRoot = process.env.NF_CACHE_DIR || path.join('data', 'cache');
const out = path.join('data', 'raw', 'gplay_top.csv');
const cache = path.join(cacheRoot, 'gplay');
fs.mkdirSync(cache, { recursive: true });
fs.mkdirSync(path.dirname(out), { recursive: true });

const CATS = ['ART_AND_DESIGN', 'AUTO_AND_VEHICLES', 'BEAUTY', 'BOOKS_AND_REFERENCE', 'BUSINESS', 'COMMUNICATION', 'DATING', 'EDUCATION',
  'ENTERTAINMENT', 'EVENTS', 'FINANCE', 'FOOD_AND_DRINK', 'HEALTH_AND_FITNESS', 'HOUSE_AND_HOME', 'LIFESTYLE', 'MAPS_AND_NAVIGATION',
  'MUSIC_AND_AUDIO', 'NEWS_AND_MAGAZINES', 'PARENTING', 'PERSONALIZATION', 'PHOTOGRAPHY', 'PRODUCTIVITY', 'SHOPPING', 'SOCIAL', 'SPORTS',
  'TOOLS', 'TRAVEL_AND_LOCAL', 'VIDEO_PLAYERS', 'WEATHER'];
const RUNS = [['us', 'en', 'TOP_GROSSING'], ['ru', 'ru', 'TOP_GROSSING'], ['ru', 'ru', 'TOP_FREE']];
const esc = v => '"' + String(v ?? '').replace(/"/g, '""').replace(/\r?\n/g, ' ') + '"';
const rows = ['country,collection,category,rank,title,appId,developer,score,priceText,summary'];
for (const [country, lang, coll] of RUNS) {
  for (const cat of CATS) {
    const key = path.join(cache, `${country}_${coll}_${cat}.json`);
    let list;
    if (fs.existsSync(key)) list = JSON.parse(fs.readFileSync(key, 'utf8'));
    else {
      try {
        list = await gplay.list({ collection: gplay.collection[coll], category: gplay.category[cat], num: 200, country, lang });
        fs.writeFileSync(key, JSON.stringify(list));
        await new Promise(r => setTimeout(r, 1500));
      } catch (e) { console.error('!!', country, coll, cat, e.message); continue; }
    }
    list.forEach((a, i) => rows.push([country, coll, cat, i + 1, a.title, a.appId, a.developer, a.scoreText, a.priceText, a.summary].map(esc).join(',')));
    console.log(country, coll, cat, list.length);
  }
}
fs.writeFileSync(out, '﻿' + rows.join('\n'), 'utf8');
console.log('->', out, rows.length - 1);
