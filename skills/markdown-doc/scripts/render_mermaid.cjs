// check_mermaid.py から呼ばれる。単独では使わない。
// 標準入力で {"diagrams":[{"id","src"}], "font": "..."} を受け取り、ヘッドレス Chromium で mermaid を描いて
// 箱・線・ラベル・文字のはみ出しの座標を JSON で標準出力に返す。判定はしない（判定は check_mermaid.py）。
// --png <dir> を付けると、各図を <dir>/<id>.png にも撮る（人が目で確かめるとき用）。
// ページからのネットワーク通信はすべて遮断する。図の内容を外部へ送らない。
// 終了コード: 0 = 返せた / 2 = playwright か mermaid が見つからない（{"error":"deps","missing":[...]} を出す）
"use strict";
const fs = require("fs");
const path = require("path");

const missing = [];
let chromium, mermaidJs;
try { ({ chromium } = require("playwright")); } catch (e) { missing.push("playwright"); }
try { mermaidJs = require.resolve("mermaid/dist/mermaid.min.js"); } catch (e) { missing.push("mermaid"); }
if (missing.length) {
  process.stdout.write(JSON.stringify({ error: "deps", missing }));
  process.exit(2);
}

const args = process.argv.slice(2);
const pngDir = args[0] === "--png" ? args[1] : null;
const input = JSON.parse(fs.readFileSync(0, "utf8"));

// ブラウザの中で動く。1枚描いて座標を集める
async function measure({ item, font }) {
  const out = document.getElementById("o");
  out.innerHTML = "";
  try {
    await mermaid.parse(item.src);
  } catch (e) {
    return { id: item.id, parseError: String((e && e.message) || e) };
  }
  let svgText;
  try {
    ({ svg: svgText } = await mermaid.render("m" + item.id, item.src));
  } catch (e) {
    return { id: item.id, parseError: String((e && e.message) || e) };
  }
  out.innerHTML = svgText;
  const svg = out.querySelector("svg");
  const vb = svg.viewBox.baseVal;
  // 縮小表示されると座標の単位がずれるので、viewBox どおりの大きさで描く
  svg.style.maxWidth = "none";
  svg.setAttribute("width", vb.width);
  svg.setAttribute("height", vb.height);
  const o = svg.getBoundingClientRect();
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return [r.left - o.left, r.top - o.top, r.width, r.height];
  };
  const text = (el) => (el.textContent || "").replace(/\s+/g, " ").trim();

  const nodes = [];
  svg.querySelectorAll("g.node").forEach((g, i) => {
    const b = box(g);
    if (b[2] > 0 && b[3] > 0) nodes.push({ i, label: text(g), box: b });
  });
  const clusters = [];
  svg.querySelectorAll("g.cluster, g.statediagram-cluster").forEach((g) => {
    const shape = g.querySelector(":scope > rect") || g.querySelector("rect") || g;
    const lab = g.querySelector(".cluster-label");
    clusters.push({ label: text(lab || g), box: box(shape), title: lab ? box(lab) : null });
  });
  const edges = [];
  svg.querySelectorAll("path[data-edge='true']").forEach((p) => {
    const len = p.getTotalLength();
    if (!(len > 0)) return;
    const m = p.getScreenCTM();
    const pts = [];
    const n = Math.max(2, Math.ceil(len / 3));
    for (let k = 0; k <= n; k++) {
      const q = p.getPointAtLength((len * k) / n);
      const s = new DOMPoint(q.x, q.y).matrixTransform(m);
      pts.push([+(s.x - o.left).toFixed(1), +(s.y - o.top).toFixed(1)]);
    }
    edges.push({ id: p.getAttribute("data-id") || p.id, points: pts });
  });
  const labels = [];
  svg.querySelectorAll("g.edgeLabel").forEach((g) => {
    const t = text(g);
    const inner = g.querySelector(".label") || g;
    const b = box(inner);
    const id = inner.getAttribute && inner.getAttribute("data-id");
    if (t && b[2] > 0 && b[3] > 0) labels.push({ edge: id || null, label: t, box: b });
  });
  // 文字のはみ出し。描いた直後と、読者側のフォントに差し替えた後の2回測る
  const clip = (phase) => {
    const res = [];
    svg.querySelectorAll("foreignObject").forEach((fo) => {
      const d = fo.firstElementChild;
      if (!d) return;
      const fw = fo.width.baseVal.value, fh = fo.height.baseVal.value;
      if (d.scrollWidth > fw + 2 || d.scrollHeight > fh + 2) {
        res.push({ phase, label: text(d), need: [d.scrollWidth, d.scrollHeight], have: [Math.round(fw), Math.round(fh)] });
      }
    });
    return res;
  };
  const clips = clip("render");
  if (font) {
    svg.querySelectorAll("foreignObject *").forEach((e) => { e.style.fontFamily = font; });
    clips.push(...clip("font"));
  }
  return {
    id: item.id,
    type: svg.getAttribute("aria-roledescription") || "",
    size: [vb.width, vb.height],
    nodes, clusters, edges, labels, clips,
  };
}

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
    // 図の中身を外へ出さない。ページからの通信はすべて止め、止めた件数を返す（mermaid は手元のファイルから読む）
    let blocked = 0;
    await page.route("**/*", (route) => { blocked++; route.abort(); });
    await page.setContent('<html><body style="margin:0"><div id="o"></div></body></html>');
    await page.addScriptTag({ path: mermaidJs });
    await page.evaluate(() => mermaid.initialize({ startOnLoad: false, securityLevel: "strict" }));
    const results = [];
    for (const item of input.diagrams) {
      const r = await page.evaluate(measure, { item, font: input.font || "" });
      if (pngDir && !r.parseError) {
        fs.mkdirSync(pngDir, { recursive: true });
        await page.locator("#o svg").screenshot({ path: path.join(pngDir, item.id + ".png") });
      }
      results.push(r);
    }
    process.stdout.write(JSON.stringify({ results, blocked }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  process.stdout.write(JSON.stringify({ error: "runtime", message: String((e && e.stack) || e) }));
  process.exit(1);
});
