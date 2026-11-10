// Drives the Strategy Builder end to end in a browser and prints what a user saw as JSON
// (used by tests/test_strategy_builder_ui.py): clone the Template, edit a parameter, switch a
// Block off, add one from the palette, save, diff, export, import and compare.
const { chromium, devices } = require("playwright");
const fs = require("fs");
const os = require("os");
const path = require("path");

(async () => {
  const [url, device, dataset] = process.argv.slice(2);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    ...(device === "mobile" ? devices["Pixel 7"] : { viewport: { width: 1280, height: 900 } }),
    acceptDownloads: true,
  });
  const page = await ctx.newPage();
  page.on("dialog", (d) => d.accept());
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  const out = {};
  const width = device === "mobile" ? 412 : 1280;  // CSS px; the zoomed-out layout width hides overflow
  let overflow = 0;
  const measure = async () => { overflow = Math.max(overflow, await page.evaluate((w) => document.documentElement.scrollWidth - w, width)); };
  const doc = async () => JSON.parse(await page.inputValue("#st-doc"));
  const status = () => page.innerText("#st-status");
  const outText = () => page.innerText("#st-out");

  await page.goto(url);
  await page.click("text=استراتژی‌ساز");
  await page.waitForSelector("#st-clone");
  await page.waitForSelector("#st-doc-blocks details.blk");
  await measure();

  // 1. clone the Template: every Block of the document has a form, the palette lists the rest
  await page.click("#st-clone");
  await page.waitForFunction(() => document.querySelector("#st-doc").value.includes("tcp_azizpour"));
  out.blockCount = await page.$$eval("#st-doc-blocks details.blk", (n) => n.length);
  out.offCount = await page.$$eval("#st-doc-blocks details.blk.off", (n) => n.length);

  // 2. edit a parameter through its form: JSON follows, the row is marked, reset undoes it
  const rsi = page.locator('details.blk[data-type="rsi_momentum"]');
  await rsi.locator("summary").click();
  const weight = rsi.locator('input[aria-label="weight"]');
  await weight.fill("2.5");
  await weight.dispatchEvent("change");
  const edited = (await doc()).blocks.find((b) => b.type === "rsi_momentum").params.weight;
  out.weightEdited = edited;
  out.rowMarked = await rsi.locator(".pf.chg").count();
  out.badge = await rsi.locator(".badge:not(.hidden)").count();

  // 3. switch a Block off (checkbox in the summary) and add one from the palette
  await page.locator('details.blk[data-type="touch_count"] summary input[type=checkbox]').uncheck();
  out.touchOff = (await doc()).blocks.find((b) => b.type === "touch_count").enabled;
  out.paletteDisabled = await page.$$eval("#st-blocks button[disabled]", (n) => n.length);
  out.paletteTotal = await page.$$eval("#st-blocks button", (n) => n.length);
  out.paletteFree = await page.$$eval("#st-blocks button:not([disabled])", (n) => n.length);
  await page.locator('details.blk[data-type="level_location"] summary button:has-text("حذف")').click();
  out.afterRemove = (await doc()).blocks.length;
  const add = page.locator('#st-blocks button[title="level_location"]');
  out.freedUp = await add.isEnabled();
  await add.click();
  out.afterAdd = (await doc()).blocks.length;
  out.addedLast = (await doc()).blocks.at(-1).type;

  // 4. a role, a risk field and a name
  await page.selectOption('#st-roles select[aria-label="hwc"]', "H4").catch(() => {});
  const risk = page.locator('#st-risk input[aria-label="risk_per_trade"]');
  await risk.fill("0.004");
  await risk.dispatchEvent("change");
  out.risk = (await doc()).risk.risk_per_trade;
  await page.fill("#st-name", "my variant");
  out.name = (await doc()).metadata.name;

  // 5. save: version 1; the same save again adds none; a change makes version 2
  await page.click("#st-save");
  await page.waitForFunction(() => document.querySelector("#st-status").innerText.includes("نسخهٔ 1"));
  out.saved1 = await status();
  await page.click("#st-save");
  await page.waitForFunction(() => document.querySelector("#st-status").innerText.includes("تغییری نبود"));
  out.saved1again = await status();
  await weight.fill("3");
  await weight.dispatchEvent("change");
  await page.click("#st-save");
  await page.waitForFunction(() => document.querySelector("#st-status").innerText.includes("نسخهٔ 2"));
  out.versions = await page.$$eval("#st-versions option", (n) => n.map((o) => o.textContent.slice(0, 7)));

  // 6. diff against the parent Template, then against the last saved version
  await page.click("#st-diff");
  await page.waitForSelector("#st-diff-out");
  out.diffParent = await page.innerText("#st-diff-out");
  await measure();
  await page.selectOption("#st-diff-base", "saved");
  await page.click("#st-diff");
  await page.waitForFunction(() => document.querySelector("#st-diff-out").innerText.includes("هیچ تفاوتی نیست"));

  // 7. open version 1 again from the version list
  await page.selectOption("#st-versions", "1");
  await page.waitForFunction(() => document.querySelector("#st-status").innerText.includes("باز شد"));
  out.v1weight = (await doc()).blocks.find((b) => b.type === "rsi_momentum").params.weight;

  // 8. export to a file, then import it back; a broken file is refused in Persian
  const [download] = await Promise.all([page.waitForEvent("download"), page.click("#st-export")]);
  const file = path.join(os.tmpdir(), "nnfx-" + process.pid + ".json");
  await download.saveAs(file);
  out.exportName = download.suggestedFilename();
  out.exported = JSON.parse(fs.readFileSync(file, "utf8")).metadata.name;
  await page.click("#st-json summary");
  await page.click("#st-sample");
  await page.setInputFiles("#st-import", file);
  await page.waitForFunction(() => document.querySelector("#st-status").innerText.includes("وارد شد"));
  out.imported = (await doc()).metadata.name;
  const bad = path.join(os.tmpdir(), "nnfx-bad-" + process.pid + ".json");
  fs.writeFileSync(bad, "{not json");
  await page.setInputFiles("#st-import", bad);
  await page.waitForFunction(() => document.querySelector("#st-out").innerText.includes("JSON"));
  out.badImport = await outText();
  await measure();
  out.badStatus = await status();

  // 9. compare the strategy with the Template on the same data
  if (dataset) {
    await page.click("#st-clone");
    await page.waitForFunction(() => document.querySelector("#st-doc").value.includes("tcp_azizpour"));
    await page.check(".st-ds");
    await page.check("#st-zero");
    await page.selectOption("#st-cmp-with", { index: 0 });
    await page.click("#st-compare");
    await page.waitForSelector("#st-cmp-out", { timeout: 60000 });
    out.compare = await page.innerText("#st-cmp-out");
    await measure();
  }

  // 10. delete
  await page.selectOption("#st-saved", "my variant");
  await page.waitForFunction(() => document.querySelector("#st-status").innerText.includes("باز شد"));
  await page.click("#st-del");
  await page.waitForFunction(() => document.querySelector("#st-status").innerText.includes("حذف شد"));
  out.deleted = await page.$$eval("#st-saved option", (n) => n.map((o) => o.value));

  await measure();
  out.overflow = overflow;
  out.errors = errors;
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: false });
  console.log(JSON.stringify(out));
  await browser.close();
})();
