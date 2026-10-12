// Headless probe for https://www.greatcirclemap.com/ – used by `python -m miles_inquiry verify-online`.
//
// Usage:  node gcm_probe.js URL [URL ...]      (needs the `playwright` npm package + a Chromium build;
//         set NODE_PATH=$(npm root -g) when playwright is installed globally)
// Output: one JSON array on stdout: [{url, expected, text, error}], where `text` is document.body.innerText.
//
// Each URL is a page like  ?routes=TPE-JFK,MZG-KHH ; the page prints "TPE ⇾ JFK\n12566 km" per route.
'use strict';
const { chromium } = require('playwright');

const urls = process.argv.slice(2);
const NAV_TIMEOUT = parseInt(process.env.GCM_PROBE_TIMEOUT_MS || '90000', 10);
const SETTLE_MS = parseInt(process.env.GCM_PROBE_SETTLE_MS || '15000', 10);

function expectedRoutes(url) {
  const m = /[?&]routes=([^&#]*)/.exec(url);
  if (!m) return 0;
  const list = decodeURIComponent(m[1]).split(',').filter(Boolean);
  return list.length;
}

(async () => {
  const results = [];
  let browser;
  try {
    browser = await chromium.launch();
  } catch (e) {
    process.stdout.write(JSON.stringify([{ url: null, error: 'launch: ' + e.message }]));
    process.exit(3);
  }
  const page = await browser.newPage();
  // Block third-party assets (maps, ads) – the distance list renders without them.
  await page.route(/google|arcgis|doubleclick|gstatic|adservice|analytics/, r => r.abort().catch(() => {}));

  for (const url of urls) {
    const expected = expectedRoutes(url);
    const item = { url, expected, text: '', error: null };
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
      // Wait until every route line has rendered (or give up after SETTLE_MS and return what we have).
      const deadline = Date.now() + SETTLE_MS;
      let text = '';
      while (Date.now() < deadline) {
        text = await page.evaluate(() => document.body.innerText);
        const n = (text.match(/⇾/g) || []).length; // '⇾'
        if (n >= expected && /\d\s*km/.test(text)) break;
        await page.waitForTimeout(400);
      }
      item.text = text;
    } catch (e) {
      item.error = e.message;
    }
    results.push(item);
  }
  await browser.close();
  process.stdout.write(JSON.stringify(results));
})().catch(e => {
  process.stdout.write(JSON.stringify([{ url: null, error: e.message }]));
  process.exit(3);
});
