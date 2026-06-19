import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let source = fs.readFileSync(path.join(root, "js", "continuity_director.js"), "utf8");
source = source.replace('import { app } from "../../scripts/app.js";', "const app = globalThis.__app;");
source = source.replace('new URL("./continuity_director.css", import.meta.url).href', '"continuity_director.css"');

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...items) { items.forEach((item) => this.values.add(item)); }
  toggle(item, enabled) { enabled ? this.values.add(item) : this.values.delete(item); }
}

class FakeElement {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.classList = new FakeClassList();
    this.hidden = false;
    this.style = {};
    this.textContent = "";
  }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.children.push(item); return item; }
  replaceChildren(...items) { this.children = [...items]; }
  querySelectorAll(selector) {
    const output = [];
    const visit = (node) => {
      if (!(node instanceof FakeElement)) return;
      if (selector === "button" && node.tagName === "BUTTON") output.push(node);
      node.children.forEach(visit);
    };
    visit(this);
    return output;
  }
  set className(value) { this._className = value; }
  get className() { return this._className || ""; }
  set innerHTML(value) { this._innerHTML = value; }
  get innerHTML() { return this._innerHTML || ""; }
}

const storage = new Map();
const sidebar = {};
const graphNodes = [];
let nextId = 1;
const graph = {
  _nodes: graphNodes,
  links: {},
  add(node) { node.id = nextId++; graphNodes.push(node); },
  remove(node) { const index = graphNodes.indexOf(node); if (index >= 0) graphNodes.splice(index, 1); },
};
const makeNode = (type) => ({
  type,
  comfyClass: type,
  title: type,
  outputs: [],
  inputs: [],
  size: type === "CDCharacterLock" ? [320, 420] : type === "CDSceneLock" ? [300, 360] : type === "CDProjectLock" ? [300, 300] : [280, 220],
  connect() { return true; },
});
let extension;

globalThis.window = globalThis;
globalThis.localStorage = {
  getItem: (key) => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, String(value)),
};
globalThis.document = {
  head: new FakeElement("head"),
  body: new FakeElement("body"),
  querySelector: () => null,
  createElement: (tag) => new FakeElement(tag),
  createTextNode: (text) => ({ textContent: String(text) }),
};
globalThis.LiteGraph = { createNode: makeNode, ROUND_SHAPE: 2 };
globalThis.__app = {
  graph,
  canvas: {
    graph_mouse: [100, 100],
    setDirty() {},
    selectNodes() {},
    fitViewToSelection() {},
    centerOnNode() {},
  },
  extensionManager: {
    registerSidebarTab(config) { sidebar.config = config; },
    toast: { add() {} },
  },
  registerExtension(config) { extension = config; },
};

const overlaps = (a, b) => {
  const [ax, ay] = a.pos;
  const [aw, ah] = a.size;
  const [bx, by] = b.pos;
  const [bw, bh] = b.size;
  return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
};

vm.runInThisContext(source, { filename: "continuity_director.js" });
if (!extension) throw new Error("frontend extension was not registered");
if (extension.name !== "continuity-director.dashboard") throw new Error("unexpected extension name");
if (extension.aboutPageBadges?.[0]?.label !== "Continuity Director v0.8.42") throw new Error("frontend version badge is stale");
await extension.setup();
if (!sidebar.config || sidebar.config.type !== "custom") throw new Error("sidebar tab was not registered");
const host = new FakeElement("aside");
sidebar.config.render(host);
if (host.children.length === 0) throw new Error("sidebar render produced no content");
const starter = extension.commands.find((item) => item.id === "continuity-director.add-starter");
if (!starter) throw new Error("starter command missing");
if (starter.function() !== true) throw new Error("starter chain did not report success");
if (graphNodes.length !== 8) throw new Error(`starter chain created ${graphNodes.length} nodes instead of 8`);
for (let left = 0; left < graphNodes.length; left += 1) {
  if (!Array.isArray(graphNodes[left].pos) || graphNodes[left].pos.length !== 2) throw new Error(`${graphNodes[left].type} has no position`);
  for (let right = left + 1; right < graphNodes.length; right += 1) {
    if (overlaps(graphNodes[left], graphNodes[right])) throw new Error(`starter nodes overlap: ${graphNodes[left].type} and ${graphNodes[right].type}`);
  }
}
console.log("frontend smoke passed: sidebar rendered, version matched, and starter layout has no overlaps");
