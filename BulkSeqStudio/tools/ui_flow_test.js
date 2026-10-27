// BulkSeq Studio UI 流程自动化验证（真实浏览器点击）
const puppeteer = require("puppeteer-core");
const fs = require("fs");

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const OUT = "D:\\Program Files\\testfield\\tmp";
const URL = "http://127.0.0.1:8600";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--window-size=1440,1000"],
    defaultViewport: { width: 1440, height: 1000 },
  });
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("requestfailed", (r) => errors.push("requestfailed: " + r.url() + " " + (r.failure() || {}).errorText));

  await page.goto(URL, { waitUntil: "networkidle2", timeout: 30000 });
  await page.screenshot({ path: `${OUT}\\flow_1_import.png` });
  console.log("[1] 首页加载完成");

  // 点击「加载示例数据」
  await page.click("#btn-example");
  await page.waitForFunction(() => {
    const el = document.querySelector("#data-summary");
    return el && !el.classList.contains("hidden") && el.innerText.includes("基因数");
  }, { timeout: 120000 });
  await sleep(600);
  await page.screenshot({ path: `${OUT}\\flow_2_summary.png`, fullPage: true });
  console.log("[2] 示例数据导入成功，概览已显示");
  // 点击「下一步」进入分析参数
  await page.click("#btn-goto-de");
  await sleep(300);

  // 点击「开始分析」
  await page.click("#btn-run-de");
  await page.waitForFunction(() => {
    const el = document.querySelector("#de-result");
    return el && !el.classList.contains("hidden");
  }, { timeout: 300000 });
  const deText = await page.evaluate(() => document.querySelector("#de-result").innerText.replace(/\s+/g, " ").slice(0, 160));
  const rowCount = await page.evaluate(() => document.querySelectorAll("#de-table tbody tr").length);
  await page.screenshot({ path: `${OUT}\\flow_3_de.png` });
  console.log("[3] 差异分析完成:", deText);
  console.log("    结果表行数:", rowCount);

  // 绘图：先切到可视化面板
  await page.click('.step[data-step="3"]');
  await page.click("#btn-plots");
  await page.waitForFunction(() => document.querySelectorAll("#plots-area .plot-card").length >= 4, { timeout: 300000 });
  const plotCount = await page.evaluate(() => document.querySelectorAll("#plots-area .plot-card").length);
  await sleep(1800);  // 等 ECharts 动画播完再截图
  await page.screenshot({ path: `${OUT}\\flow_4_plots.png`, fullPage: true });
  console.log("[4] 图表生成:", plotCount, "个");

  // 自定义尺寸：修改火山图尺寸并重新生成
  const beforeSize = await page.evaluate(() => {
    const i = document.querySelector("#card-volcano img");
    return { w: i.naturalWidth, h: i.naturalHeight, src: i.src };
  });
  await page.click("#card-volcano .card-actions a:nth-child(3)");  // ⚙ 自定义尺寸
  await page.evaluate(() => {
    document.querySelector("#w-volcano").value = "1400";
    document.querySelector("#h-volcano").value = "1200";
    document.querySelector("#dpi-volcano").value = "150";
  });
  await page.click("#card-volcano .size-bar .btn");
  await page.evaluate(() => document.querySelector("#card-volcano").scrollIntoView({ block: "center" }));
  const oldSearch = "?" + (beforeSize.src.split("?")[1] || "");
  await page.waitForFunction((oldQ) => {
    const i = document.querySelector("#card-volcano img");
    return i && i.complete && i.naturalWidth > 0 && !i.src.includes(oldQ);
  }, { timeout: 120000, polling: 500 }, oldSearch);
  const afterSize = await page.evaluate(() => {
    const i = document.querySelector("#card-volcano img");
    return { w: i.naturalWidth, h: i.naturalHeight };
  });
  console.log(`[4b] 火山图自定义尺寸: ${beforeSize.w}x${beforeSize.h} -> ${afterSize.w}x${afterSize.h} px`,
    (afterSize.w !== beforeSize.w || afterSize.h !== beforeSize.h) ? "OK" : "FAIL");
  await page.screenshot({ path: `${OUT}\\flow_4b_resize.png`, fullPage: true });

  // 快速保存：PNG / PDF（按当前 1400x1200 尺寸）
  const DL = `${OUT}\\downloads`;
  if (fs.existsSync(DL)) fs.readdirSync(DL).forEach(f => fs.unlinkSync(`${DL}\\${f}`));
  else fs.mkdirSync(DL, { recursive: true });
  const client = await page.target().createCDPSession();
  await client.send("Page.setDownloadBehavior", { behavior: "allow", downloadPath: DL });

  await page.click("#card-volcano .card-actions a:nth-child(1)");  // PNG
  await sleep(6000);
  await page.click("#card-volcano .card-actions a:nth-child(2)");  // PDF
  await sleep(8000);
  const files = fs.readdirSync(DL).map(f => ({ f, kb: Math.round(fs.statSync(`${DL}\\${f}`).size / 1024) }));
  console.log("[4c] 保存文件:", JSON.stringify(files));

  // PCA 交互图：设尺寸 1000x500 后保存 PNG
  await page.evaluate(() => {
    document.querySelector("#pca-echart-w").value = "1000";
    document.querySelector("#pca-echart-h").value = "500";
    applyChartSize("pca-echart");
  });
  await sleep(600);
  await page.evaluate(() => saveChart("pca-echart", "PCA_interactive", "png"));
  await sleep(4000);
  const pcaFile = fs.readdirSync(DL).find(f => f.startsWith("PCA_interactive"));
  console.log("[4d] PCA 交互图保存:", pcaFile);

  // 单基因查询（可视化面板内的入口）
  await page.evaluate(() => { document.querySelector("#inp-gene2").value = "PTGS2"; });
  await page.click("#btn-gene-detail2");
  await page.waitForFunction(() => document.querySelector("#gene-plot-area img"), { timeout: 60000 });
  await page.screenshot({ path: `${OUT}\\flow_5_gene.png`, fullPage: true });
  console.log("[5] 单基因图生成 OK");

  // 富集：先切到富集面板
  await page.click('.step[data-step="4"]');
  await page.click("#btn-enrich");
  await page.waitForFunction(() => {
    const el = document.querySelector("#enrich-result");
    return el && !el.classList.contains("hidden");
  }, { timeout: 300000 });
  const enrichRows = await page.evaluate(() => document.querySelectorAll("#enrich-table tbody tr").length);
  // 图表切换：默认气泡图 → 截图 → 切条形图 → 截图
  const chartType0 = await page.evaluate(() => document.querySelector("#sel-enrich-chart")?.value);
  await sleep(2000);
  await page.screenshot({ path: `${OUT}\\flow_6_enrich_bubble.png`, fullPage: true });
  await page.select("#sel-enrich-chart", "bar");
  await sleep(1500);
  await page.screenshot({ path: `${OUT}\\flow_6_enrich_bar.png`, fullPage: true });
  console.log("[6] 富集完成，条目数:", enrichRows, "| 默认图表类型:", chartType0);

  // 富集交互图自定义尺寸
  await page.evaluate(() => {
    document.querySelector("#ew-inp").value = "1400";
    document.querySelector("#eh-inp").value = "600";
  });
  await page.click("#enrich-chart-card .btn");
  await sleep(800);
  const eW = await page.evaluate(() => Math.round(document.querySelector("#enrich-echart").getBoundingClientRect().width));
  const eH = await page.evaluate(() => Math.round(document.querySelector("#enrich-echart").getBoundingClientRect().height));
  console.log("[6b] 富集图自定义尺寸:", eW, "x", eH, (eW === 1400 && eH === 600) ? "OK" : "FAIL");

  // 交互图（PCA / 富集）保存 PNG + PDF
  await page.evaluate(() => saveChart("enrich-echart", "enrichment", "pdf"));
  await sleep(6000);
  const files2 = fs.readdirSync(DL).map(f => ({ f, kb: Math.round(fs.statSync(`${DL}\\${f}`).size / 1024) }));
  console.log("[6c] 交互图保存:", JSON.stringify(files2.filter(x => /PCA|enrich/.test(x.f))));

  console.log("\n=== JS 错误 ===");
  if (errors.length === 0) console.log("无");
  else errors.slice(0, 12).forEach((e) => console.log(" -", e));

  await browser.close();
})().catch(async (e) => {
  console.error("TEST FAILED:", e.message);
  process.exit(1);
});
