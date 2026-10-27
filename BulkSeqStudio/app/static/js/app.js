/* BulkSeq Studio 前端逻辑 */
const SID = Math.random().toString(36).slice(2) + Date.now().toString(36);
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let state = {
  summary: null,
  deResult: null,
  interactive: {},
  engines: null,
  plotSizes: {},          // 每张图的自定义尺寸 {key: {w, h, dpi}}
  chartSizes: {},         // 交互图（ECharts）画布尺寸 {chartId: {w, h}}
  enrichChartType: "bubble",
  enrichChartSize: null,  // 富集交互图尺寸 {w, h}
  geneQuery: "",
};

/* ---------------- 工具 ---------------- */
function toast(msg, type = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 3500);
}
async function api(path, data, isForm = true) {
  let opts;
  if (isForm) {
    const fd = new FormData();
    for (const [k, v] of Object.entries(data)) fd.append(k, v);
    opts = { method: "POST", body: fd };
  } else {
    opts = { method: "GET" };
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res;
}
function setStep(n, done = true) {
  $$(".step").forEach(el => {
    const v = +el.dataset.step;
    el.classList.toggle("active", v === n);
    if (done && v < n) el.classList.add("done");
  });
  $$(".panel").forEach(el => el.classList.toggle("active", el.id === "panel-" + n));
}
function fmtNum(v, digits = 4) {
  if (v === null || v === undefined || v === "" ) return "";
  const n = parseFloat(v);
  if (isNaN(n)) return v;
  if (n !== 0 && Math.abs(n) < 0.001) return n.toExponential(2);
  return n.toFixed(digits);
}
/* 给图片 URL 追加时间戳，避免浏览器缓存旧图 */
function bust(url) {
  if (!url) return url;
  return url + (url.includes("?") ? "&t=" : "?t=") + Date.now();
}

/* 图片加载失败时自动换一种 URL 形式重试（部分代理会丢弃查询串，反之亦然） */
function imgFallback(el) {
  const src = el.getAttribute("src") || "";
  const name = (src.match(/[0-9a-f]{8,}\.png/i) || [])[0];
  const tried = +(el.dataset.retry || 0);
  if (name && tried === 0) {
    el.dataset.retry = "1";
    el.src = `/api/figure?name=${name}&t=${Date.now()}`;
    return;
  }
  el.dataset.failed = "1";
  el.style.display = "none";
  if (el.parentElement && !el.parentElement.querySelector(".img-fail")) {
    const box = document.createElement("div");
    box.className = "warn-box img-fail";
    box.innerHTML = `图片加载失败（${escapeHtml(name || src)}）——
      <a href="javascript:void 0" onclick="this.closest('.plot-card').querySelector('img').style.display='';
        this.closest('.plot-card').querySelector('img').dataset.retry='0';
        this.closest('.plot-card').querySelector('img').src='/api/figure/${name}?t=' + Date.now();
        this.parentElement.remove();">重试</a>`;
    el.parentElement.appendChild(box);
  }
}

/* ---------------- 初始化 ---------------- */
window.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await api("/api/info", null, false);
    const info = await res.json();
    state.engines = info.engines;
    const e = info.engines;
    let txt = [];
    if (e.r_available) txt.push(`R ✓ (${e.methods.DESeq2 ? "DESeq2 ✓" : "DESeq2 ✗"}, edgeR ✓, limma ✓)`);
    else txt.push("R 未检测到");
    txt.push(e.pydeseq2_available ? "pydeseq2 ✓" : "pydeseq2 ✗");
    $("#engine-status").textContent = "引擎状态：" + txt.join(" · ");
    if (!e.methods.DESeq2) $("#sel-method option[value=DESeq2]").disabled = true;
    if (!e.methods.edgeR) $("#sel-method option[value=edgeR]").disabled = true;
    if (!e.methods.limma) $("#sel-method option[value=limma]").disabled = true;
    if (!e.methods.pydeseq2) $("#sel-method option[value=pydeseq2]").disabled = true;
  } catch (err) {
    $("#engine-status").textContent = "引擎检测失败";
  }

  $("#btn-upload").onclick = () => uploadFiles(false);
  $("#btn-example").onclick = () => uploadFiles(true);
  $("#btn-run-de").onclick = runDE;
  $("#btn-plots").onclick = runPlots;
  $("#btn-enrich").onclick = runEnrich;
  $("#btn-export-excel").onclick = exportExcel;
  $("#btn-export-html").onclick = exportHtml;
  $("#btn-gene-detail").onclick = () => viewGene("inp-gene-search");
  $("#btn-gene-detail2").onclick = () => viewGene("inp-gene2");
  $("#btn-goto-de").onclick = () => setStep(2);
  $("#inp-gene-search").oninput = () => renderDeTable();
  $("#sel-enrich-mode").onchange = () => {
    $("#gmt-label").classList.toggle("hidden", $("#sel-enrich-mode").value !== "gmt");
  };
  $$(".step").forEach(el => {
    el.onclick = () => {
      const n = +el.dataset.step;
      if (n === 1) return setStep(1);
      if (!state.summary) return toast("请先导入数据", "error");
      if (n >= 3 && !state.deResult) return toast("请先完成差异分析", "error");
      setStep(n);
    };
  });

  setStep(1);  // 确保首屏显示数据导入面板
});

/* ---------------- Step 1 导入 ---------------- */
async function uploadFiles(useExample) {
  const fd = { session_id: SID, use_example: String(useExample) };
  if (!useExample) {
    const f1 = $("#file-counts").files[0];
    if (!f1) { toast("请选择表达矩阵文件", "error"); return; }
    fd.counts = f1;
    const f2 = $("#file-meta").files[0];
    if (f2) fd.metadata = f2;
  }
  try {
    $("#btn-upload").disabled = $("#btn-example").disabled = true;
    const res = await api("/api/upload", fd);
    const data = await res.json();
    state.summary = data.summary;
    showSummary(data);
    fillRefSelect();
    setStep(1);  // 留在导入页，便于用户确认概览与警告
    $("#btn-goto-de").classList.remove("hidden");
    toast("数据导入成功 ✓ 请确认概览后点击「下一步」", "ok");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    $("#btn-upload").disabled = $("#btn-example").disabled = false;
  }
}

function showSummary(data) {
  const s = data.summary;
  let groupBadges = Object.entries(s.groups).map(([g, n]) =>
    `<span class="badge">${g} × ${n}</span>`).join("");
  let warn = "";
  const warns = [...(s.warnings || []), ...(data.source ? [] : [])];
  if (warns.length) {
    warn = `<div class="warn-box">⚠ ${warns.map(w => escapeHtml(w)).join("<br>⚠ ")}</div>`;
  }
  $("#data-summary").className = "";
  $("#data-summary").innerHTML = `
    <h3>数据概览 <span class="badge">${escapeHtml(data.source || "")}</span></h3>
    <div class="summary-grid">
      <div class="stat"><div class="v">${s.n_genes}</div><div class="k">基因数</div></div>
      <div class="stat"><div class="v">${s.n_samples}</div><div class="k">样本数</div></div>
      <div class="stat"><div class="v">${Object.keys(s.groups).length}</div><div class="k">分组数</div></div>
    </div>
    <div>${groupBadges}</div>${warn}`;

  // 第 2 步里放一份精简概览，避免切换面板后看不到
  $("#data-summary-mini").className = "mini-summary";
  $("#data-summary-mini").innerHTML = `
    <span class="badge">${s.n_genes} 基因</span>
    <span class="badge">${s.n_samples} 样本</span>${groupBadges}
    ${warn}`;
}

function fillRefSelect() {
  const sel = $("#sel-ref");
  sel.innerHTML = "";
  const groups = Object.keys(state.summary.groups);
  groups.forEach(g => {
    const opt = document.createElement("option");
    opt.value = g; opt.textContent = g;
    sel.appendChild(opt);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

/* ---------------- Step 2 差异分析 ---------------- */
async function runDE() {
  const fd = {
    session_id: SID,
    method: $("#sel-method").value,
    alpha: $("#inp-alpha").value,
    lfc: $("#inp-lfc").value,
    ref_group: $("#sel-ref").value || "",
  };
  $("#btn-run-de").disabled = true;
  $("#de-progress").classList.remove("hidden");
  try {
    const res = await api("/api/analyze", fd);
    const data = await res.json();
    state.deResult = data.result;
    state.summary = data.summary;
    showDEResult(data.result);
    renderDeTable();
    setStep(2);  // 停留在差异分析面板，便于查看结果表
    toast(`分析完成 ✓ 上调 ${data.result.n_sig_up} / 下调 ${data.result.n_sig_down}`, "ok");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    $("#btn-run-de").disabled = false;
    $("#de-progress").classList.add("hidden");
  }
}

function showDEResult(r) {
  $("#de-result").className = "";
  $("#de-result").innerHTML = `
    <h3>差异分析结果 <span class="badge">${escapeHtml(r.engine)}</span>
      <span class="badge">${escapeHtml(r.alt)} vs ${escapeHtml(r.ref)}</span></h3>
    <div class="summary-grid">
      <div class="stat"><div class="v up">${r.n_sig_up}</div><div class="k">显著上调基因</div></div>
      <div class="stat"><div class="v down">${r.n_sig_down}</div><div class="k">显著下调基因</div></div>
      <div class="stat"><div class="v">${r.rows.length}</div><div class="k">检测基因总数</div></div>
      <div class="stat"><div class="v">${Object.keys(r.size_factors).length}</div><div class="k">样本（已归一化）</div></div>
    </div>
    <p class="hint">阈值：padj &lt; ${r.alpha} 且 |log2FC| ≥ ${r.lfc_threshold}</p>`;
  $("#de-table-wrap").classList.remove("hidden");
}

function renderDeTable() {
  const r = state.deResult;
  if (!r) return;
  const q = $("#inp-gene-search").value.trim().toUpperCase();
  const cols = r.columns;
  const idx = { gene: 0, baseMean: 1, log2FC: 2, lfcSE: 3, stat: 4, pvalue: 5, padj: 6 };
  let rows = r.rows;
  if (q) rows = rows.filter(row => String(row[0]).toUpperCase().includes(q));
  rows = rows.slice(0, 300);

  let html = "<thead><tr>";
  ["基因", "baseMean", "log2FC", "lfcSE", "stat", "p-value", "padj"].forEach(h => html += `<th>${h}</th>`);
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    const lfc = row[idx.log2FC], padj = row[idx.padj];
    const cls = (padj !== null && padj < 0.05 && lfc !== null) ? (lfc > 0 ? "up" : "down") : "";
    html += `<tr><td>${escapeHtml(row[0])}</td><td>${fmtNum(row[1], 1)}</td>
      <td class="${cls}">${fmtNum(lfc)}</td><td>${fmtNum(row[3])}</td><td>${fmtNum(row[4])}</td>
      <td>${fmtNum(row[5])}</td><td>${fmtNum(row[6])}</td></tr>`;
  }
  html += "</tbody>";
  $("#de-table").innerHTML = html;
}

/* ---------------- Step 3 可视化 ---------------- */
/* 各图默认尺寸（px @150dpi），可在卡片上自定义 */
const PLOT_DEFS = {
  pca:     { title: "PCA 主成分分析", w: 1050, h: 825 },
  corr:    { title: "样本相关性",     w: 900,  h: 750 },
  dist:    { title: "表达分布",       w: 900,  h: 750 },
  volcano: { title: "火山图",         w: 1125, h: 900 },
  ma:      { title: "MA 图",          w: 1125, h: 825 },
  heatmap: { title: "差异基因热图",   w: 1050, h: 900 },
};

function plotSizeOf(key) {
  const d = PLOT_DEFS[key];
  const s = state.plotSizes[key] || {};
  return { w: s.w || d.w, h: s.h || d.h, dpi: s.dpi || 150 };
}

function plotCardHtml(key, url) {
  const d = PLOT_DEFS[key], s = plotSizeOf(key);
  return `<div class="plot-card" id="card-${key}">
    <div class="title">${d.title}
      <span class="card-actions">
        <a href="javascript:void 0" onclick="savePlot('${key}','png')">⤓ PNG</a>
        <a href="javascript:void 0" onclick="savePlot('${key}','pdf')">⤓ PDF</a>
        <a href="javascript:void 0" onclick="toggleSizeBar('${key}')">⚙ 自定义尺寸</a>
      </span>
    </div>
    <div class="size-bar hidden" id="sizebar-${key}">
      宽 <input type="number" id="w-${key}" value="${s.w}" min="200" max="6000" step="10"> px
      高 <input type="number" id="h-${key}" value="${s.h}" min="150" max="6000" step="10"> px
      DPI <input type="number" id="dpi-${key}" value="${s.dpi}" min="72" max="600" step="1">
      <button class="btn" onclick="applyPlotSize('${key}')">应用并重新生成</button>
      <span class="size-hint">改尺寸后仅重绘此图</span>
    </div>
    <img src="${bust(url)}" loading="lazy" onerror="imgFallback(this)">
  </div>`;
}

/* 保存单张静态图为 PNG / PDF（按当前自定义尺寸重新出图） */
async function savePlot(key, fmt) {
  const title = key === "gene" ? "单基因图" : (PLOT_DEFS[key] ? PLOT_DEFS[key].title : key);
  toast(`正在生成 ${title} 的 ${fmt.toUpperCase()}…`);
  const fd = { session_id: SID, key, fmt, sizes: JSON.stringify(state.plotSizes) };
  if (key === "gene") fd.gene = state.geneQuery || $("#inp-gene-search").value.trim();
  try {
    const res = await api("/api/plots/export", fd);
    const blob = await res.blob();
    const s = key === "gene" ? (state.plotSizes.gene || {}) : (state.plotSizes[key] || {});
    const dim = s.w && s.h ? `_${s.w}x${s.h}` : "";
    const dpiTag = fmt === "pdf" ? "vector" : `${s.dpi || 150}dpi`;
    downloadBlob(blob, `${key}${dim}_${dpiTag}.${fmt}`);
    toast(`${title} 已保存为 ${fmt.toUpperCase()} ✓`, "ok");
  } catch (err) {
    toast(err.message, "error");
  }
}

/* 交互图（ECharts）通用尺寸调整：按输入框设置画布大小并 resize */
function applyChartSize(chartId) {
  const el = document.getElementById(chartId);
  const inst = el && echarts.getInstanceByDom(el);
  if (!inst) return;
  const w = +($(`#${chartId}-w`) || {}).value || 0;
  const h = +($(`#${chartId}-h`) || {}).value || 0;
  state.chartSizes[chartId] = { w: w || null, h: h || 380 };
  el.style.width = w ? w + "px" : "100%";
  el.style.height = (h || 380) + "px";
  inst.resize();
  toast("图表尺寸已更新 ✓", "ok");
}

/* 保存交互图（ECharts 画布）：PNG 直接取画布，PDF 交服务端按同尺寸封装 */
async function saveChart(elId, name, fmt) {
  const el = document.getElementById(elId);
  const inst = el && echarts.getInstanceByDom(el);
  if (!inst) { toast("图表尚未渲染完成", "error"); return; }
  const w = Math.round(inst.getWidth() || el.getBoundingClientRect().width);
  const h = Math.round(inst.getHeight() || el.getBoundingClientRect().height);
  const dataUrl = inst.getDataURL({ type: "png", pixelRatio: 1, backgroundColor: "#ffffff" });
  const blob = await (await fetch(dataUrl)).blob();
  if (fmt === "png") {
    downloadBlob(blob, `${name}_${w}x${h}.png`);
    toast("PNG 已保存 ✓", "ok");
    return;
  }
  try {
    const fd = new FormData();
    fd.append("file", blob, "chart.png");
    fd.append("w_px", w); fd.append("h_px", h);
    const res = await fetch("/api/image/pdf", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || "PDF 生成失败");
    downloadBlob(await res.blob(), `${name}_${w}x${h}.pdf`);
    toast("PDF 已保存 ✓", "ok");
  } catch (err) {
    toast(err.message, "error");
  }
}

function toggleSizeBar(key) {
  $(`#sizebar-${key}`).classList.toggle("hidden");
}

async function applyPlotSize(key) {
  const w = +$(`#w-${key}`).value, h = +$(`#h-${key}`).value;
  const dpi = Math.round(+$(`#dpi-${key}`).value) || 150;
  if (!(w >= 200 && h >= 150 && dpi >= 72)) { toast("请输入有效尺寸（宽≥200px、高≥150px、DPI≥72）", "error"); return; }
  state.plotSizes[key] = { w, h, dpi };
  const card = $(`#card-${key}`);
  card.style.opacity = "0.45";
  try {
    const res = await api("/api/plots", { session_id: SID, only: key, sizes: JSON.stringify(state.plotSizes) });
    const data = await res.json();
    if (data.plots[key]) {
      const img = card.querySelector("img");
      img.dataset.retry = "0"; img.style.display = "";
      img.src = bust(data.plots[key]);
      const fail = card.querySelector(".img-fail"); if (fail) fail.remove();
      toast(`「${PLOT_DEFS[key].title}」已按 ${w}×${h}px @${dpi}dpi 重新生成 ✓`, "ok");
    } else {
      toast(data.errors?.[key] || "生成失败", "error");
    }
  } catch (err) {
    toast(err.message, "error");
  } finally {
    card.style.opacity = "";
  }
}

async function runPlots() {
  $("#btn-plots").disabled = true;
  $("#plot-progress").classList.remove("hidden");
  $("#plots-area").innerHTML = "";
  try {
    const res = await api("/api/plots", { session_id: SID, plot_set: "all",
      sizes: JSON.stringify(state.plotSizes) });
    const data = await res.json();
    state.interactive = data.interactive || {};
    let html = "";
    for (const key of ["pca", "corr", "volcano", "ma", "heatmap", "dist"]) {
      if (data.plots[key]) {
        html += plotCardHtml(key, data.plots[key]);
      } else if (data.errors && data.errors[key]) {
        html += `<div class="plot-card"><div class="title">${PLOT_DEFS[key].title}</div>
          <div class="warn-box">无法生成：${escapeHtml(data.errors[key])}</div></div>`;
      }
    }
    $("#plots-area").innerHTML = html;
    // PCA 交互图
    if (state.interactive.pca) renderPcaEchart(state.interactive.pca);
    setStep(3);  // 停留在可视化面板，不自动跳走
    toast("图表生成完成 ✓", "ok");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    $("#btn-plots").disabled = false;
    $("#plot-progress").classList.add("hidden");
  }
}

function renderPcaEchart(d) {
  const uniq = [...new Set(d.groups)];
  const series = uniq.map(g => ({
    name: g, type: "scatter",
    data: d.samples.map((s, i) => d.groups[i] === g ? [d.pc1[i], d.pc2[i], s] : null).filter(Boolean),
    itemStyle: { color: d.colors[g] },
    label: { show: true, formatter: (p) => p.value[2], position: "right", fontSize: 10, color: "#666" },
  }));
  const div = document.createElement("div");
  div.className = "plot-card";
  const sz = state.chartSizes["pca-echart"] || {};
  div.innerHTML = `<div class="title">PCA 交互图（悬停查看样本）
      <span class="card-actions">
        <a href="javascript:void 0" onclick="saveChart('pca-echart','PCA_interactive','png')">⤓ PNG</a>
        <a href="javascript:void 0" onclick="saveChart('pca-echart','PCA_interactive','pdf')">⤓ PDF</a>
        <a href="javascript:void 0" onclick="toggleSizeBar('pca-echart')">⚙ 自定义尺寸</a>
      </span>
    </div>
    <div class="size-bar hidden" id="sizebar-pca-echart">
      宽 <input type="number" id="pca-echart-w" value="${sz.w || ""}" placeholder="auto" min="320" max="6000"> px
      高 <input type="number" id="pca-echart-h" value="${sz.h || 380}" min="240" max="6000"> px
      <button class="btn" onclick="applyChartSize('pca-echart')">应用</button>
      <span class="size-hint">保存的 PNG/PDF 按此尺寸输出</span>
    </div>
    <div class="plot-echart" id="pca-echart"
      ${sz.w ? `style="width:${sz.w}px;height:${sz.h || 380}px"` : ""}></div>`;
  $("#plots-area").prepend(div);
  const chart = echarts.init($("#pca-echart"));
  chart.setOption({
    tooltip: { formatter: p => `${p.value[2]}<br>PC1: ${p.value[0]}<br>PC2: ${p.value[1]}` },
    legend: { top: 5 },
    grid: { left: 60, bottom: 50 },
    xAxis: { name: `PC1 (${d.var1}%)`, type: "value" },
    yAxis: { name: `PC2 (${d.var2}%)`, type: "value" },
    series,
  });
}

async function viewGene(inputId = "inp-gene-search") {
  const gene = ($("#" + inputId).value || $("#inp-gene-search").value || "").trim();
  if (!gene) { toast("请先输入基因名，例如 PTGS2", "error"); return; }
  if (!state.deResult) { toast("请先完成差异分析", "error"); return; }
  state.geneQuery = gene;
  try {
    const res = await api("/api/gene_plot", { session_id: SID, gene,
      sizes: JSON.stringify(state.plotSizes) });
    const d = await res.json();
    const st = d.stats || {};
    const fmt = (v) => (v === null || v === undefined) ? "—" : fmtNum(v, 4);
    const cls = (st.log2FoldChange ?? 0) > 0 ? "up" : "down";
    const s = state.plotSizes.gene || { w: 1500, h: 675, dpi: 150 };
    $("#gene-plot-area").innerHTML = `
      <div class="plot-card" style="margin-top:18px;" id="card-gene">
        <div class="title">基因 ${escapeHtml(d.gene)} 表达详情
          <span class="card-actions">
            <a href="javascript:void 0" onclick="savePlot('gene','png')">⤓ PNG</a>
            <a href="javascript:void 0" onclick="savePlot('gene','pdf')">⤓ PDF</a>
            <a href="javascript:void 0" onclick="toggleSizeBar('gene')">⚙ 自定义尺寸</a>
          </span>
        </div>
        <div class="hint" style="margin-bottom:8px;">
          log2FC = <b class="${cls}">${fmt(st.log2FoldChange)}</b> ·
          padj = <b>${fmt(st.padj)}</b> · baseMean = ${fmt(st.baseMean)}
        </div>
        <div class="size-bar hidden" id="sizebar-gene">
          宽 <input type="number" id="w-gene" value="${s.w}" min="200" max="6000" step="10"> px
          高 <input type="number" id="h-gene" value="${s.h}" min="150" max="6000" step="10"> px
          DPI <input type="number" id="dpi-gene" value="${s.dpi}" min="72" max="600" step="1">
          <button class="btn" onclick="applyGeneSize()">应用并重新生成</button>
        </div>
        <img src="${bust(d.image)}" onerror="imgFallback(this)">
      </div>`;
    setStep(3, false);
    $("#gene-plot-area").scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (err) {
    toast(err.message, "error");
  }
}

async function applyGeneSize() {
  const w = +$("#w-gene").value, h = +$("#h-gene").value;
  const dpi = Math.round(+$("#dpi-gene").value) || 150;
  if (!(w >= 200 && h >= 150 && dpi >= 72)) { toast("请输入有效尺寸", "error"); return; }
  state.plotSizes.gene = { w, h, dpi };
  const card = $("#card-gene");
  card.style.opacity = "0.45";
  try {
    const res = await api("/api/gene_plot", { session_id: SID, gene: state.geneQuery,
      sizes: JSON.stringify(state.plotSizes) });
    const d = await res.json();
    const img = card.querySelector("img");
    img.dataset.retry = "0"; img.style.display = "";
    img.src = bust(d.image);
    const fail = card.querySelector(".img-fail"); if (fail) fail.remove();
    toast(`单基因图已按 ${w}×${h}px @${dpi}dpi 重新生成 ✓`, "ok");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    card.style.opacity = "";
  }
}

/* ---------------- Step 4 富集 ---------------- */
async function runEnrich() {
  const fd = {
    session_id: SID,
    library: $("#sel-library").value,
    direction: $("#sel-direction").value,
    mode: $("#sel-enrich-mode").value,
    gmt_path: $("#inp-gmt").value.trim(),
    cutoff: 0.05,
  };
  $("#btn-enrich").disabled = true;
  $("#enrich-progress").classList.remove("hidden");
  try {
    const res = await api("/api/enrich", fd);
    const data = await res.json();
    state.enrichData = data;
    showEnrich(data);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    $("#btn-enrich").disabled = false;
    $("#enrich-progress").classList.add("hidden");
  }
}

function showEnrich(d) {
  $("#enrich-result").className = "";
  $("#enrich-result").innerHTML = `<h3>富集结果 <span class="badge">查询基因 ${d.n_query}</span>
    <span class="badge">显著通路 ${d.n_total}</span></h3>`;
  let html = "<thead><tr><th>#</th><th>通路 / 条目</th><th>Overlap</th><th>P-value</th><th>padj</th><th>富集得分</th><th>基因</th></tr></thead><tbody>";
  d.terms.forEach((t, i) => {
    html += `<tr><td>${i + 1}</td><td>${escapeHtml(t.term)}</td><td>${t.overlap}</td>
      <td>${fmtNum(t.p)}</td><td>${fmtNum(t.padj)}</td><td>${t.score}</td>
      <td style="max-width:340px;white-space:normal">${escapeHtml(t.genes)}</td></tr>`;
  });
  html += "</tbody>";
  $("#enrich-table").innerHTML = html;
  if (d.terms.length) renderEnrichChart(d);
  setStep(4);  // 停留在富集面板，便于查看结果
}

/* 富集图：气泡图（默认）/ 条形图，可切换；支持自定义画布尺寸 */
function renderEnrichChart(d) {
  const old = document.querySelector("#enrich-chart-card");
  if (old) { echarts.dispose(old); old.remove(); }
  const sz = state.enrichChartSize || {};
  const div = document.createElement("div");
  div.className = "plot-card";
  div.id = "enrich-chart-card";
  div.style.marginTop = "18px";
  div.innerHTML = `<div class="title" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
      <span>Top 15 富集条目</span>
      <select id="sel-enrich-chart" style="font-size:12px;padding:2px 6px;">
        <option value="bubble"${(state.enrichChartType || "bubble") === "bubble" ? " selected" : ""}>气泡图</option>
        <option value="bar"${state.enrichChartType === "bar" ? " selected" : ""}>条形图</option>
      </select>
      <span style="margin-left:auto;font-weight:400;font-size:12px;">
        宽 <input type="number" id="ew-inp" value="${sz.w || ""}" placeholder="auto" min="320" max="6000" style="width:64px;font-size:12px;"> px
        高 <input type="number" id="eh-inp" value="${sz.h || ""}" placeholder="auto" min="240" max="6000" style="width:64px;font-size:12px;"> px
        <button class="btn" style="padding:2px 10px;font-size:12px;" onclick="applyEnrichChartSize()">应用</button>
        <a href="javascript:void 0" style="margin-left:6px;" onclick="saveChart('enrich-echart','enrichment','png')">⤓ PNG</a>
        <a href="javascript:void 0" style="margin-left:6px;" onclick="saveChart('enrich-echart','enrichment','pdf')">⤓ PDF</a>
      </span>
    </div><div class="plot-echart" id="enrich-echart"
      ${sz.w ? `style="width:${sz.w}px;height:${sz.h || 380}px"` : ""}></div>`;
  $("#enrich-result").after(div);
  $("#sel-enrich-chart").onchange = (e) => {
    state.enrichChartType = e.target.value;   // 记住用户选择
    setEnrichOption(e.target.value);
  };
  setEnrichOption($("#sel-enrich-chart").value);
}

function applyEnrichChartSize() {
  const w = +$("#ew-inp").value, h = +$("#eh-inp").value;
  if ((!w || w >= 320) && (!h || h >= 240)) {
    state.enrichChartSize = { w: w || null, h: h || 380 };
  }
  renderEnrichChart(state.enrichData);   // 重建卡片以应用尺寸
  toast("富集图尺寸已更新 ✓", "ok");
}

function setEnrichOption(mode) {
  const d = state.enrichData;
  if (!d) return;
  const top = d.terms.slice(0, 15).reverse();
  const terms = top.map(t => t.term.length > 40 ? t.term.slice(0, 38) + "…" : t.term);
  // overlap 形如 "12/112"：k=通路内命中的差异基因数，n=通路基因总数
  const parseOv = t => { const m = String(t.overlap).split("/"); return { k: +m[0] || 0, n: +m[1] || 0 }; };
  const ov = $("#enrich-echart");
  echarts.dispose(ov);                 // 彻底重建，避免两种图的 option 相互残留
  const chart = echarts.init(ov);
  chart.setOption({
    tooltip: { formatter: p => `${p.name}<br>-log10(padj): ${p.data.lgc.toFixed(2)}<br>
      基因: ${p.data.k}/${p.data.n} (${p.data.ratio}%)<br>${p.data.genes}`.replace(/\n\s*/g, "<br>") },
    grid: { left: 250, right: 110, top: 20, bottom: 45 },
    xAxis: { type: "value", nameLocation: "middle", nameGap: 28,
             name: mode === "bubble" ? "富集倍率 (%)" : "-log10(padj)" },
    yAxis: { type: "category", data: terms, axisLabel: { fontSize: 11 } },
    visualMap: {
      min: 0, max: Math.max(...top.map(t => t.score)), left: "right", top: "middle",
      text: ["-log10(padj)", ""], calculable: false, itemHeight: 90,
      inRange: { color: ["#e34a33", "#fdbb84", "#7fcdbb"] },
    },
    series: [mode === "bubble" ? {
      name: "富集", type: "scatter",
      data: top.map(t => {
        const { k, n } = parseOv(t);
        return { value: n ? +(k / n * 100).toFixed(2) : 0, name: t.term, k, n,
                 ratio: n ? (k / n * 100).toFixed(1) : "0", lgc: t.score, genes: t.genes,
                 symbolSize: 8 + Math.sqrt(k) * 7 };
      }),
    } : {
      name: "富集", type: "bar",
      data: top.map(t => {
        const { k, n } = parseOv(t);
        return { value: t.score, name: t.term, k, n,
                 ratio: n ? (k / n * 100).toFixed(1) : "0", lgc: t.score, genes: t.genes };
      }),
      label: { show: true, position: "right", fontSize: 10,
               formatter: p => p.data.lgc.toFixed(2) },
      itemStyle: { borderRadius: [0, 3, 3, 0] },
    }],
  });
}

/* ---------------- Step 5 导出 ---------------- */
async function exportExcel() {
  try {
    toast("正在生成 Excel…");
    const res = await api("/api/report/excel", { session_id: SID });
    const blob = await res.blob();
    downloadBlob(blob, "bulkseq_report.xlsx");
    toast("Excel 已导出 ✓", "ok");
  } catch (err) { toast(err.message, "error"); }
}
async function exportHtml() {
  try {
    toast("正在生成 HTML 报告…");
    const res = await api("/api/report/html", { session_id: SID, project_name: $("#inp-project").value });
    const blob = await res.blob();
    downloadBlob(blob, "bulkseq_report.html");
    toast("HTML 报告已导出 ✓", "ok");
  } catch (err) { toast(err.message, "error"); }
}
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
