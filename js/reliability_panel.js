import { app } from "../../scripts/app.js";

const NODES = [
  ["CDVerifyPackage", "Verify Package", "校验生产包"],
  ["CDMigratePayload", "Migrate Payload", "迁移数据结构"],
  ["CDRetryPolicy", "Retry Policy", "重试策略"],
  ["CDQueueCheckpoint", "Queue Checkpoint", "队列断点"],
  ["CDIdempotencyKey", "Idempotency Key", "幂等键"],
  ["CDEnvironmentLock", "Environment Lock", "环境锁"],
];

const addNode = (type) => {
  const node = window.LiteGraph?.createNode?.(type);
  if (!node || !app.graph) return;
  node.pos = Array.isArray(app.canvas?.graph_mouse) ? [...app.canvas.graph_mouse] : [200, 200];
  app.graph.add(node);
  app.canvas?.setDirty?.(true, true);
};

const render = (host) => {
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
    button.innerHTML = `<span class="cd-node-icon"><i class="pi pi-shield"></i></span><span class="cd-node-copy"><b>${en} / ${zh}</b><small>${type}</small></span><i class="pi pi-plus"></i>`;
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
  },
});
