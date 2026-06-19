import { app } from "../../scripts/app.js";

const NAME = "continuity-director.dashboard";
const VER = "0.8.22";
const KEY = "continuity-director.language";
const STARTER_GAP_X = 120;
const STARTER_GAP_Y = 80;
const MIN_NODE_WIDTH = 280;
const MIN_NODE_HEIGHT = 180;

const groups = {
  locks: [["CDProjectLock", "projectLock", "pi-folder"], ["CDCharacterLock", "characterLock", "pi-user"], ["CDSceneLock", "sceneLock", "pi-map-marker"], ["CDShotLock", "shotLock", "pi-video"], ["CDManifestBuilder", "manifest", "pi-box"]],
  directing: [["CDBatchDirector", "batchDirector", "pi-sitemap"], ["CDReferenceHandoff", "referenceHandoff", "pi-link"]],
  quality: [["CDQualityGate", "qualityGate", "pi-shield"], ["CDTakeRanker", "takeRanker", "pi-sort-amount-down"], ["CDContinuityReport", "continuityReport", "pi-search"]],
  runtime: [["CDExecutionPlan", "executionPlan", "pi-bolt"]],
  collaboration: [["CDAuditEvent", "auditEvent", "pi-history"], ["CDThreeWayMerge", "threeWayMerge", "pi-code-branch"]],
  export: [["CDExportPackage", "exportPackage", "pi-download"]],
  reliability: [["CDVerifyPackage", "verifyPackage", "pi-check-circle"], ["CDMigratePayload", "migratePayload", "pi-sync"], ["CDRetryPolicy", "retryPolicy", "pi-refresh"], ["CDQueueCheckpoint", "queueCheckpoint", "pi-save"], ["CDIdempotencyKey", "idempotencyKey", "pi-key"], ["CDEnvironmentLock", "environmentLock", "pi-lock"]],
};

const en = {title:"Continuity Director",subtitle:"Production continuity control",overview:"Overview",nodes:"Nodes",guide:"Guide",language:"Language",cdNodes:"CD nodes",connections:"Connections",projectState:"Project state",ready:"Ready",empty:"Not configured",quickStart:"Quick start",quickStartHint:"Add the core production chain to the current workflow.",addStarter:"Add starter chain",fitNodes:"Focus CD nodes",nodeLibrary:"Node library",pipeline:"Recommended pipeline",health:"Workflow health",noNodes:"No Continuity Director nodes in this workflow.",active:"Active",locks:"Continuity locks",directing:"Directing",quality:"Quality",runtime:"Runtime",collaboration:"Collaboration",export:"Export",reliability:"Reliability",step1:"Lock project, characters, scenes, and shots.",step2:"Build a manifest and expand storyboard takes.",step3:"Rank takes and block failed quality gates.",step4:"Create execution waves, audit decisions, and export.",docs:"Open documentation",added:"Node added",starterAdded:"Starter chain added",projectLock:"Project Lock",characterLock:"Character Lock",sceneLock:"Scene Lock",shotLock:"Shot Lock",manifest:"Manifest Builder",batchDirector:"Batch Director",referenceHandoff:"Reference Handoff",qualityGate:"Quality Gate",takeRanker:"Take Ranker",continuityReport:"Continuity Report",executionPlan:"Execution Plan",auditEvent:"Audit Event",threeWayMerge:"Three-Way Merge",exportPackage:"Export Package",verifyPackage:"Verify Package",migratePayload:"Migrate Payload",retryPolicy:"Retry Policy",queueCheckpoint:"Queue Checkpoint",idempotencyKey:"Idempotency Key",environmentLock:"Environment Lock"};
const zh = {title:"连续性导演",subtitle:"AI 视频生产连续性控制台",overview:"总览",nodes:"节点",guide:"流程指南",language:"语言",cdNodes:"插件节点",connections:"连接数",projectState:"项目状态",ready:"可用",empty:"未配置",quickStart:"快速开始",quickStartHint:"向当前工作流添加一套核心生产链。",addStarter:"添加入门链",fitNodes:"聚焦插件节点",nodeLibrary:"节点库",pipeline:"推荐流程",health:"工作流状态",noNodes:"当前工作流还没有连续性导演节点。",active:"已启用",locks:"连续性锁",directing:"导演编排",quality:"质量控制",runtime:"运行计划",collaboration:"协作审计",export:"导出",reliability:"可靠性",step1:"锁定项目、角色、场景和镜头。",step2:"生成清单，并将分镜扩展为多个 Take。",step3:"对 Take 排名，并阻止未通过质量门的结果。",step4:"生成执行波次、记录审计事件并导出。",docs:"打开文档",added:"节点已添加",starterAdded:"入门链已添加",projectLock:"项目锁",characterLock:"角色锁",sceneLock:"场景锁",shotLock:"镜头锁",manifest:"清单构建器",batchDirector:"批量导演",referenceHandoff:"参考帧承接",qualityGate:"质量门",takeRanker:"Take 排名",continuityReport:"连续性报告",executionPlan:"执行计划",auditEvent:"审计事件",threeWayMerge:"三方合并",exportPackage:"导出生产包",verifyPackage:"校验生产包",migratePayload:"迁移数据结构",retryPolicy:"重试策略",queueCheckpoint:"队列断点",idempotencyKey:"幂等键",environmentLock:"环境锁"};

const lang = () => ["en", "zh-CN", "bilingual"].includes(localStorage.getItem(KEY)) ? localStorage.getItem(KEY) : "en";
const t = (key, language = lang()) => language === "bilingual" ? `${en[key] || key} / ${zh[key] || en[key] || key}` : language === "zh-CN" ? (zh[key] || en[key] || key) : (en[key] || key);
const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
const ic = (name) => el("i", `pi ${name || "pi-circle"}`);

function css() {
  if (document.querySelector("link[data-cd-style]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./continuity_director.css", import.meta.url).href;
  link.dataset.cdStyle = "1";
  document.head.append(link);
}

function isCD(node) {
  return String(node?.comfyClass || node?.type || "").startsWith("CD");
}

function stats() {
  const nodes = (app.graph?._nodes || []).filter(isCD);
  const ids = new Set(nodes.map((node) => node.id));
  let links = 0;
  for (const node of nodes) for (const output of node.outputs || []) for (const id of output.links || []) {
    const link = app.graph?.links?.[id];
    if (link && ids.has(link.target_id)) links += 1;
  }
  return { nodes, links };
}

function toast(summary, detail = "") {
  app.extensionManager?.toast?.add?.({ severity: "success", summary, detail, life: 2000 });
}

function center() {
  const canvas = app.canvas;
  if (Array.isArray(canvas?.graph_mouse)) return [...canvas.graph_mouse];
  const scale = canvas?.ds?.scale || 1;
  const offset = canvas?.ds?.offset || [0, 0];
  return [(canvas?.canvas?.width || 1200) / 2 / scale - offset[0], (canvas?.canvas?.height || 800) / 2 / scale - offset[1]];
}

function style(node) {
  if (!isCD(node)) return;
  const type = node.comfyClass || node.type || "";
  const palette = type.includes("Quality") || type.includes("Report") || type.includes("Ranker") ? ["#0f766e", "#102f2f"] : type.includes("Audit") || type.includes("Merge") ? ["#7c3aed", "#281b3d"] : type.includes("Verify") || type.includes("Migrate") || type.includes("Retry") || type.includes("Checkpoint") || type.includes("Idempotency") || type.includes("Environment") ? ["#0369a1", "#102a43"] : type.includes("Export") ? ["#c2410c", "#3b2015"] : ["#1d4ed8", "#172554"];
  node.color = palette[0];
  node.bgcolor = palette[1];
  node.shape = window.LiteGraph?.ROUND_SHAPE ?? node.shape;
  node.size = [Math.max(node.size?.[0] || MIN_NODE_WIDTH, MIN_NODE_WIDTH), Math.max(node.size?.[1] || MIN_NODE_HEIGHT, MIN_NODE_HEIGHT)];
}

function add(type, pos, notify = true) {
  const node = window.LiteGraph?.createNode?.(type);
  if (!node || !app.graph) return null;
  style(node);
  node.pos = pos || center();
  app.graph.add(node);
  app.canvas?.setDirty?.(true, true);
  if (notify) toast(t("added"), node.title || type);
  return node;
}

function dimensions(node) {
  return [Math.max(Number(node?.size?.[0]) || 0, MIN_NODE_WIDTH), Math.max(Number(node?.size?.[1]) || 0, MIN_NODE_HEIGHT)];
}

function layoutStarter(nodes, base) {
  const columns = [
    ["CDProjectLock", "CDCharacterLock", "CDSceneLock"],
    ["CDShotLock"],
    ["CDManifestBuilder"],
    ["CDBatchDirector"],
    ["CDExecutionPlan", "CDExportPackage"],
  ];
  const metrics = columns.map((types) => {
    const columnNodes = types.map((type) => nodes.get(type)).filter(Boolean);
    const sizes = columnNodes.map(dimensions);
    return {
      nodes: columnNodes,
      sizes,
      width: Math.max(...sizes.map(([width]) => width), MIN_NODE_WIDTH),
      height: sizes.reduce((total, [, height]) => total + height, 0) + Math.max(0, sizes.length - 1) * STARTER_GAP_Y,
    };
  });
  const totalWidth = metrics.reduce((total, item) => total + item.width, 0) + Math.max(0, metrics.length - 1) * STARTER_GAP_X;
  let x = base[0] - totalWidth / 2;
  for (const column of metrics) {
    let y = base[1] - column.height / 2;
    column.nodes.forEach((node, index) => {
      const [, height] = column.sizes[index];
      node.pos = [Math.round(x), Math.round(y)];
      y += height + STARTER_GAP_Y;
    });
    x += column.width + STARTER_GAP_X;
  }
}

function starter() {
  const base = center();
  const types = ["CDProjectLock", "CDCharacterLock", "CDSceneLock", "CDShotLock", "CDManifestBuilder", "CDBatchDirector", "CDExecutionPlan", "CDExportPackage"];
  const nodes = new Map();
  for (const type of types) nodes.set(type, add(type, base, false));
  layoutStarter(nodes, base);
  const connect = (source, output, target, input) => nodes.get(source)?.connect?.(output, nodes.get(target), input);
  connect("CDProjectLock", 0, "CDShotLock", 0);
  connect("CDSceneLock", 0, "CDShotLock", 1);
  connect("CDCharacterLock", 0, "CDShotLock", 2);
  connect("CDProjectLock", 0, "CDManifestBuilder", 0);
  connect("CDCharacterLock", 0, "CDManifestBuilder", 1);
  connect("CDSceneLock", 0, "CDManifestBuilder", 2);
  connect("CDShotLock", 0, "CDManifestBuilder", 3);
  connect("CDManifestBuilder", 0, "CDBatchDirector", 0);
  connect("CDBatchDirector", 0, "CDExecutionPlan", 0);
  connect("CDManifestBuilder", 0, "CDExportPackage", 0);
  connect("CDBatchDirector", 0, "CDExportPackage", 1);
  connect("CDExecutionPlan", 0, "CDExportPackage", 2);
  app.canvas?.setDirty?.(true, true);
  toast(t("starterAdded"));
}

function focus() {
  const nodes = stats().nodes;
  if (!nodes.length) return;
  if (nodes.length === 1) return app.canvas?.centerOnNode?.(nodes[0]);
  app.canvas?.selectNodes?.(nodes);
  app.canvas?.fitViewToSelection?.();
  app.canvas?.setDirty?.(true, true);
}

function button(label, kind, handler, icon) {
  const item = el("button", `cd-button ${kind}`);
  item.append(ic(icon), document.createTextNode(label));
  item.onclick = handler;
  return item;
}

function header(host, language) {
  const wrapper = el("header", "cd-header");
  const brand = el("div", "cd-brand");
  const mark = el("div", "cd-mark");
  mark.innerHTML = '<span class="cd-ring"></span><span class="cd-core"></span>';
  const copy = el("div", "cd-brand-copy");
  copy.append(el("strong", "", t("title", language)), el("span", "", t("subtitle", language)));
  brand.append(mark, copy);
  const select = document.createElement("select");
  select.className = "cd-language";
  for (const [value, label] of [["en", "English"], ["zh-CN", "中文"], ["bilingual", "EN / 中文"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = language === value;
    select.append(option);
  }
  select.onchange = () => { localStorage.setItem(KEY, select.value); render(host); };
  wrapper.append(brand, select);
  return wrapper;
}

function metric(icon, label, value, state = "") {
  const wrapper = el("div", `cd-metric ${state}`);
  const visual = el("div", "cd-metric-icon");
  const copy = el("div", "cd-metric-copy");
  visual.append(ic(icon));
  copy.append(el("b", "", String(value)), el("span", "", label));
  wrapper.append(visual, copy);
  return wrapper;
}

function overview(language) {
  const state = stats();
  const view = el("section", "cd-view");
  const metrics = el("div", "cd-metrics");
  metrics.append(metric("pi-box", t("cdNodes", language), state.nodes.length), metric("pi-share-alt", t("connections", language), state.links), metric(state.nodes.length ? "pi-check-circle" : "pi-minus-circle", t("projectState", language), t(state.nodes.length ? "ready" : "empty", language), state.nodes.length ? "ok" : "idle"));
  const quick = el("div", "cd-card");
  const quickCopy = el("div");
  quickCopy.append(el("h3", "", t("quickStart", language)), el("p", "", t("quickStartHint", language)));
  const actions = el("div", "cd-actions");
  actions.append(button(t("addStarter", language), "primary", starter, "pi-plus"), button(t("fitNodes", language), "secondary", focus, "pi-expand"));
  quick.append(quickCopy, actions);
  const health = el("div", "cd-card");
  health.append(el("h3", "", t("health", language)));
  const row = el("div", "cd-health");
  row.append(el("span", `cd-dot ${state.nodes.length ? "ok" : "idle"}`), el("span", "", state.nodes.length ? t("active", language) : t("noNodes", language)));
  health.append(row);
  view.append(metrics, quick, health);
  return view;
}

function library(language) {
  const view = el("section", "cd-view");
  const head = el("div", "cd-section-head");
  head.append(el("h3", "", t("nodeLibrary", language)), el("span", "cd-chip", `v${VER}`));
  view.append(head);
  for (const [key, list] of Object.entries(groups)) {
    const group = el("div", "cd-group");
    const groupHead = el("div", "cd-group-head");
    groupHead.append(el("span", "", t(key, language)), el("span", "cd-chip", String(list.length)));
    group.append(groupHead);
    for (const [type, label, icon] of list) {
      const item = el("button", "cd-node-button");
      const visual = el("span", "cd-node-icon");
      const copy = el("span", "cd-node-copy");
      visual.append(ic(icon));
      copy.append(el("b", "", t(label, language)), el("small", "", type));
      item.append(visual, copy, ic("pi-plus"));
      item.onclick = () => add(type);
      group.append(item);
    }
    view.append(group);
  }
  return view;
}

function guide(language) {
  const view = el("section", "cd-view");
  const timeline = el("div", "cd-timeline");
  view.append(el("h3", "", t("pipeline", language)));
  ["step1", "step2", "step3", "step4"].forEach((key, index) => {
    const row = el("div", "cd-step");
    row.append(el("span", "cd-step-no", String(index + 1)), el("p", "", t(key, language)));
    timeline.append(row);
  });
  view.append(timeline, button(t("docs", language), "secondary", () => window.open("https://github.com/xinjian0101/continuity-director", "_blank", "noopener,noreferrer"), "pi-external-link"));
  return view;
}

function render(host) {
  if (!host) return;
  const language = lang();
  const root = el("div", "cd-dashboard");
  const tabs = el("nav", "cd-tabs");
  const main = el("main", "cd-content");
  const views = { overview: overview(language), nodes: library(language), guide: guide(language) };
  host.replaceChildren();
  host.classList.add("cd-host");
  root.append(header(host, language));
  let active = host.dataset.cdTab || "overview";
  const show = (id) => {
    active = id;
    host.dataset.cdTab = id;
    tabs.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item.dataset.tab === id));
    main.replaceChildren(views[id]);
  };
  for (const [id, icon] of [["overview", "pi-chart-bar"], ["nodes", "pi-th-large"], ["guide", "pi-compass"]]) {
    const item = el("button", "cd-tab");
    item.dataset.tab = id;
    item.append(ic(icon), document.createTextNode(t(id, language)));
    item.onclick = () => show(id);
    tabs.append(item);
  }
  root.append(tabs, main, el("footer", "cd-footer", `Continuity Director v${VER} · 20 nodes`));
  host.append(root);
  show(active);
}

function fallback() {
  if (document.querySelector(".cd-launcher")) return;
  const launcher = el("button", "cd-launcher", "CD");
  const panel = el("aside", "cd-floating");
  panel.hidden = true;
  launcher.onclick = () => { panel.hidden = !panel.hidden; if (!panel.hidden) render(panel); };
  document.body.append(launcher, panel);
}

app.registerExtension({
  name: NAME,
  aboutPageBadges: [{ label: `Continuity Director v${VER}`, url: "https://github.com/xinjian0101/continuity-director", icon: "pi pi-video" }],
  commands: [
    { id: "continuity-director.add-starter", label: "Continuity Director: Add starter chain", icon: "pi pi-plus", function: starter },
    { id: "continuity-director.focus", label: "Continuity Director: Focus nodes", icon: "pi pi-expand", function: focus },
  ],
  menuCommands: [{ path: ["Continuity Director"], commands: ["continuity-director.add-starter", "continuity-director.focus"] }],
  keybindings: [{ combo: { key: "D", ctrl: true, shift: true }, commandId: "continuity-director.add-starter" }],
  async setup() {
    css();
    try {
      if (app.extensionManager?.registerSidebarTab) app.extensionManager.registerSidebarTab({ id: "continuity-director", icon: "pi pi-video", title: "Continuity Director", tooltip: "Continuity Director", type: "custom", render });
      else fallback();
    } catch (error) {
      console.warn("[Continuity Director] sidebar fallback", error);
      fallback();
    }
  },
  nodeCreated: style,
  loadedGraphNode: style,
});
