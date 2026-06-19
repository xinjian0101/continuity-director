import { app } from "../../scripts/app.js";

const VERSION = "0.7.0";
const COLORS = {
  CDWorkflowTemplate: ["#2c4a3b", "#1b3126"],
  CDWorkflowBind: ["#5a3d25", "#3d2818"],
  CDRunSnapshot: ["#67451f", "#422d16"],
  CDQueueState: ["#67451f", "#422d16"],
  CDQueueClaim: ["#67451f", "#422d16"],
  CDQueueReap: ["#553033", "#391f22"],
  CDAssetIndex: ["#30485b", "#1f303d"],
  CDQualityGate: ["#2c4a3b", "#1b3126"],
  CDQualityEvaluate: ["#553033", "#391f22"],
  CDTakeSelection: ["#553033", "#391f22"],
  CDRemakePlan: ["#5f3730", "#3f241f"],
  CDTraceEvent: ["#4f3b25", "#342719"],
  CDTraceSummary: ["#4f3b25", "#342719"],
  CDRunBundlePackage: ["#30485b", "#1f303d"],
  CDRunBundleVerify: ["#27505a", "#19353b"],
  CDOneClickDirector: ["#5b4925", "#3c3018"],
  CDProjectLock: ["#23334d", "#162236"],
  CDCharacterLock: ["#3d2d57", "#291d3d"],
  CDCastLock: ["#493263", "#302142"],
  CDSceneLock: ["#2c4a3b", "#1b3126"],
  CDShotDirector: ["#5a3d25", "#3d2818"],
  CDBatchDirector: ["#5a3d25", "#3d2818"],
  CDTakeVariants: ["#66451f", "#422d16"],
  CDContinuityAudit: ["#553033", "#391f22"],
  CDSequenceAudit: ["#553033", "#391f22"],
  CDSequenceRepair: ["#5f3730", "#3f241f"],
  CDProductionReport: ["#4f3b25", "#342719"],
  CDManifestValidator: ["#553033", "#391f22"],
  CDManifestMigrate: ["#553033", "#391f22"],
  CDProviderExport: ["#30485b", "#1f303d"],
  CDSaveManifest: ["#30485b", "#1f303d"],
  CDPackageProject: ["#30485b", "#1f303d"],
  CDPackageVerify: ["#27505a", "#19353b"],
  CDReferenceRegistry: ["#3d2d57", "#291d3d"],
  CDReferenceStatus: ["#3d2d57", "#291d3d"],
  CDPresencePlan: ["#5a3d25", "#3d2818"],
  CDSequenceTimeline: ["#5a3d25", "#3d2818"],
  CDDependencyGraph: ["#5a3d25", "#3d2818"],
  CDRetryPolicy: ["#5a3d25", "#3d2818"],
  CDModelProfile: ["#2c4a3b", "#1b3126"],
  CDReferenceSelector: ["#5a3d25", "#3d2818"],
  CDExecutionPlan: ["#67451f", "#422d16"],
  CDTaskReconcile: ["#553033", "#391f22"],
  CDFailureClassifier: ["#553033", "#391f22"],
  CDExecutionDiagnostics: ["#4f3b25", "#342719"],
};

function setting(id, fallback) {
  try {
    const value = app.extensionManager?.setting?.get(id);
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

function invalidJsonWidgets(node) {
  if (!setting("ContinuityDirector.UI.jsonWarnings", true)) return [];
  return (node.widgets || []).filter((widget) => {
    if (!widget?.name?.toLowerCase().includes("json")) return false;
    const value = String(widget.value ?? "").trim();
    if (!value) return false;
    try {
      JSON.parse(value);
      return false;
    } catch {
      return true;
    }
  });
}

app.registerExtension({
  name: "continuity.director.ui",
  settings: [
    {
      id: "ContinuityDirector.UI.showBadge",
      name: "显示版本徽标",
      category: ["Continuity Director", "界面", "显示版本徽标"],
      type: "boolean",
      defaultValue: true,
      tooltip: "在节点右上角显示 Continuity Director 版本。",
    },
    {
      id: "ContinuityDirector.UI.jsonWarnings",
      name: "JSON 即时警告",
      category: ["Continuity Director", "界面", "JSON 即时警告"],
      type: "boolean",
      defaultValue: true,
      tooltip: "JSON 输入格式错误时在节点标题栏显示红色提示。",
    },
    {
      id: "ContinuityDirector.UI.compactNodes",
      name: "紧凑节点宽度",
      category: ["Continuity Director", "界面", "紧凑节点宽度"],
      type: "boolean",
      defaultValue: false,
      tooltip: "新建节点使用较窄的默认宽度；不会修改已经保存的工作流尺寸。",
    },
  ],
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const palette = COLORS[nodeData.name];
    if (!palette) return;

    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      originalCreated?.apply(this, arguments);
      this.color = palette[0];
      this.bgcolor = palette[1];
      const compact = setting("ContinuityDirector.UI.compactNodes", false);
      const minWidth = compact ? 320 : 380;
      this.size = [Math.max(this.size?.[0] || minWidth, minWidth), this.size?.[1] || 120];
    };

    const originalDraw = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function (ctx) {
      originalDraw?.apply(this, arguments);
      if (this.flags?.collapsed) return;

      if (setting("ContinuityDirector.UI.showBadge", true)) {
        const label = `CD ${VERSION}`;
        ctx.save();
        ctx.font = "10px sans-serif";
        const width = ctx.measureText(label).width + 12;
        ctx.globalAlpha = 0.78;
        ctx.fillStyle = "#111827";
        ctx.fillRect(this.size[0] - width - 7, 5, width, 16);
        ctx.globalAlpha = 1;
        ctx.fillStyle = "#f3f4f6";
        ctx.fillText(label, this.size[0] - width - 1, 17);
        ctx.restore();
      }

      const invalid = invalidJsonWidgets(this);
      if (invalid.length) {
        ctx.save();
        ctx.fillStyle = "#ef4444";
        ctx.beginPath();
        ctx.arc(12, 12, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = "10px sans-serif";
        ctx.fillStyle = "#fecaca";
        ctx.fillText(`${invalid.length} 个 JSON 输入无效`, 22, 16);
        ctx.restore();
      }
    };
  },
});
