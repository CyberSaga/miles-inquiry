// Screenshot each route on https://www.greatcirclemap.com/ – used by `python -m miles_inquiry screenshots`.
//
// Usage:  node gcm_screenshot.js JOBS.json      (needs the `playwright` npm package + a Chromium build;
//         set NODE_PATH=$(npm root -g) when playwright is installed globally)
// JOBS.json: {"width":1280,"height":800,"jobs":[{"url":"https://www.greatcirclemap.com/?routes=TPE-JFK","path":"/abs/out.png"}]}
// Output: one JSON array on stdout: [{url, path, text, captured_at, error}], `text` = document.body.innerText.
//
// A strip with the page URL and capture time is added at the bottom of each image (a browser screenshot
// has no address bar); it is labelled as added by this tool and does not cover the route list or the map.
'use strict';
const fs = require('fs');
const { chromium } = require('playwright');

const NAV_TIMEOUT = parseInt(process.env.GCM_PROBE_TIMEOUT_MS || '90000', 10);
const SETTLE_MS = parseInt(process.env.GCM_PROBE_SETTLE_MS || '15000', 10);
const RENDER_MS = parseInt(process.env.GCM_SHOT_RENDER_MS || '1500', 10);

function stamp(d) {
  const p = n => String(n).padStart(2, '0');
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const oh = p(Math.floor(Math.abs(off) / 60)), om = p(Math.abs(off) % 60);
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())} UTC${sign}${oh}:${om}`;
}

(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const results = [];
  let browser;
  try {
    browser = await chromium.launch();
  } catch (e) {
    process.stdout.write(JSON.stringify([{ url: null, error: 'launch: ' + e.message }]));
    process.exit(3);
  }
  const page = await browser.newPage({ viewport: { width: spec.width || 1280, height: spec.height || 800 } });
  // Block ads/analytics only; the default globe view needs nothing else from third parties.
  await page.route(/doubleclick|adservice|googlesyndication|google-analytics|googletagmanager/, r => r.abort().catch(() => {}));

  for (const job of spec.jobs) {
    const item = { url: job.url, path: job.path, text: '', captured_at: null, error: null };
    try {
      await page.goto(job.url, { waitUntil: 'networkidle', timeout: NAV_TIMEOUT });
      const deadline = Date.now() + SETTLE_MS;
      let text = '';
      while (Date.now() < deadline) {
        text = await page.evaluate(() => document.body.innerText);
        if ((/⇾/.test(text) && /\d\s*km/.test(text)) || /does not exist in our database/.test(text)) break;
        await page.waitForTimeout(400);
      }
      await page.waitForTimeout(RENDER_MS); // let the globe finish drawing the arc
      const capturedAt = stamp(new Date());
      await page.evaluate(([url, when]) => {
        const old = document.getElementById('miles-inquiry-evidence');
        if (old) old.remove();
        const div = document.createElement('div');
        div.id = 'miles-inquiry-evidence';
        div.textContent = `來源 ${url}　｜　擷取時間 ${when}　｜　（此列為 miles_inquiry 加註）`;
        Object.assign(div.style, {
          position: 'fixed', left: '300px', right: '0', bottom: '0', zIndex: 99999,
          background: 'rgba(0,0,0,0.78)', color: '#fff', font: '13px/1.6 sans-serif',
          padding: '4px 10px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        });
        document.body.appendChild(div);
      }, [job.url, capturedAt]);
      await page.screenshot({ path: job.path });
      item.text = text;
      item.captured_at = capturedAt;
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
