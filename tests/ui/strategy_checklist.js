// Drives the Strategy Builder tab in a real browser and prints what a user sees
// of the first candidate's checklist as JSON (used by tests/test_strategy_ui.py).
const { chromium, devices } = require("playwright");

(async () => {
  const [url, docJson, device] = process.argv.slice(2);
  const browser = await chromium.launch();
  const ctx = await browser.newContext(device === "mobile" ? devices["Pixel 7"] : { viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(url);
  await page.click("text=استراتژی‌ساز");
  await page.waitForSelector(".st-ds");
  await page.fill("#st-doc", docJson);
  await page.check(".st-ds");
  await page.check("#st-zero");
  await page.click("#st-run");
  await page.waitForSelector("details.cand");
  await page.click("details.cand summary");
  const rows = await page.$$eval("details.cand[open] table tr", (trs) =>
    trs.slice(1).map((tr) => [...tr.querySelectorAll("td")].map((td) => td.innerText.trim())));
  const path = await page.$$eval("details.cand[open] .path .chip", (cs) => cs.map((c) => c.className.replace("chip st-", "")));
  const summary = await page.innerText("details.cand summary");
  const result = await page.innerText("#st-out .panel");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(JSON.stringify({ rows, path, summary, result, overflow, errors }));
  await browser.close();
})();
