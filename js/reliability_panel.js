import { app } from "../../scripts/app.js";

const NODES = [
  ["CDVerifyPackage", "Verify Package", "校验生产包"],
  ["CDMigratePayload", "Migrate Payload", "迁移数据结构"],
  ["CDRetryPolicy", "Retry Policy", "重试策略"],
  ["CDQueueCheckpoint", "Queue Checkpoint", "队列断点"],
  ["CDIdempotencyKey", "Idempotency Key", "幂等键"],
  ["CDEnvironmentLock", "Environment Lock", "环境锁"],
];

const finitePair = (value) => Array.isArray(value)
  && value.length >= 2
  && Number.isFinite(Number(value[0]))
  && Number.isFinite(Number(value[1]));

const notify = (summary, detail = "", severity = "success") => {
  app.extensionManager?.toast?.add?.({ severity, summary, detail, life: severity === "error" ? 4000 : 2000 });
};

const addNode = (type) => {
  try {
    const node = window.LiteGraph?.createNode?.(type);
    if (!node || !app.graph?.add) throw new Error(`Unable to create ${type}`);
    const cursor = app.canvas?.graph_mouse;
    node.pos = finitePair(cursor) ? [Number(cursor[0]), Number(cursor[1])] : [200, 200];
    const width = Number(node.size?.[0]);
    const height = Number(node.size?.[1]);
    node.size = [Number.isFinite(width) ? Math.max(width, 280) : 280, Number.isFinite(height) ? Math.max(height, 180) : 180];
    node.color = node.color || "#0369a1";
    node.bgcolor = node.bgcolor || "#102a43";
    app.graph.add(node);
    app.canvas?.setDirty?.(true, true);
    notify("Reliability node added", node.title || type);
    return true;
  } catch (error) {
    console.error("[Continuity Director] reliability node creation failed", type, error);
    notify("Reliability node creation failed", String(error?.message || type), "error");
    return false;
  }
};

const render = (host) => {
  if (!host?.replaceChildren) return;
  host.replaceChildren();
  const root = document.createElement("div");
  root.className = "cd-view";
  const title = document.createElement("h3");
  title.textContent = "Reliability / 可靠性";
  root.append(title);
  for (const [type, en, zh] of NODES) {
    const button = document.createElement("button");
    button.className = "cd-node-button";
    button.type = "button";
    const icon = document.createElement("span");
    icon.className = "cd-node-icon";
    icon.innerHTML = '<i class="pi pi-shield"></i>';
    const copy = document.createElement("span");
    copy.className = "cd-node-copy";
    const label = document.createElement("b");
    label.textContent = `${en} / ${zh}`;
    const code = document.createElement("small");
    code.textContent = type;
    copy.append(label, code);
    const plus = document.createElement("i");
    plus.className = "pi pi-plus";
    button.append(icon, copy, plus);
    button.addEventListener("click", () => addNode(type));
    root.append(button);
  }
  host.append(root);
};

app.registerExtension({
  name: "continuity-director.reliability",
  settings: [
    {
      id: "ContinuityDirector.ShowReliabilityTab",
      name: "Continuity Director: Show reliability tab",
      type: "boolean",
      defaultValue: true,
    },
  ],
  commands: NODES.map(([type, en]) => ({
    id: `continuity-director.add.${type}`,
    label: `Continuity Director: Add ${en}`,
    function: () => addNode(type),
  })),
  menuCommands: [
    {
      path: ["Continuity Director", "Reliability"],
      commands: NODES.map(([type]) => `continuity-director.add.${type}`),
    },
  ],
  async setup() {
    try {
      const visible = app.extensionManager?.setting?.get?.("ContinuityDirector.ShowReliabilityTab") ?? true;
      if (!visible || !app.extensionManager?.registerSidebarTab) return;
      app.extensionManager.registerSidebarTab({
        id: "continuity-director-reliability",
        icon: "pi pi-shield",
        title: "CD Reliability",
        tooltip: "Continuity Director reliability tools",
        type: "custom",
        render,
      });
    } catch (error) {
      console.error("[Continuity Director] reliability sidebar setup failed", error);
      notify("Reliability sidebar setup failed", String(error?.message || error), "error");
    }
  },
});
