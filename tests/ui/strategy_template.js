// Picks the TCP Template in the Strategy Builder tab, clones it into the editor, and prints
// what a user sees as JSON (used by tests/test_strategy_templates.py).
const { chromium, devices } = require("playwright");

(async () => {
  const [url, device] = process.argv.slice(2);
  const browser = await chromium.launch();
  const ctx = await browser.newContext(device === "mobile" ? devices["Pixel 7"] : { viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(url);
  await page.click("text=استراتژی‌ساز");
  await page.waitForSelector("#st-clone");
  const detail = await page.innerText("#st-template-detail");
  await page.click("#st-template-detail summary");
  const rows = await page.$$eval("#st-template-detail tr", (trs) => trs.map((tr) => [...tr.querySelectorAll("td")].map((td) => td.innerText.trim())));
  await page.click("#st-clone");
  await page.waitForFunction(() => document.querySelector("#st-doc").value.includes("tcp_azizpour"));
  const doc = JSON.parse(await page.inputValue("#st-doc"));
  await page.click("#st-validate");
  await page.waitForFunction(() => !document.querySelector("#st-out").innerText.includes("را اعتبارسنجی یا بک"));
  const verdict = await page.innerText("#st-out");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(JSON.stringify({ detail, rows, doc, verdict, overflow, errors }));
  await browser.close();
})();
