# Continuity Director

面向 AI 短视频生产的 ComfyUI 一致性、编排、质检与多人协作插件。

插件不替代视频模型。它把角色、服装、道具、场景、镜头、种子、参考帧、任务队列、审批记录和生成环境固化为可复现数据，降低人物漂移、跨镜变化和多人协作冲突。

## v0.7.0 能力概览

| 模块 | 作用 |
|---|---|
| 连续性锁 | 固定项目、角色、演员表、场景、镜头、状态和种子 |
| 批量导演 | 从分镜 JSON 批量生成连续镜头链和 Take |
| 运行编排 | 依赖 DAG、并行波次、持久队列、任务租约和失败恢复 |
| 参考帧 | 参考帧生命周期、自动择优和首尾帧承接 |
| 质量闭环 | 技术质检、外部身份指标、边界连续性、选优和定向重做 |
| 后期治理 | 视频探测、抽帧、拼接、快照、差异、回滚和血缘追踪 |
| 多人协作 | 角色权限、编辑锁、审批流、变更请求和生成放行门 |
| 分布式执行 | 工作节点注册、心跳、能力匹配和容量调度 |
| 供应链安全 | 环境锁文件、模板包校验、发布者信任和无密钥配置包 |
| 可复现验证 | 审计哈希链、故障注入、回归基线和运行重放比较 |

当前包含 **95 个 ComfyUI 节点**，Manifest Schema 为 **1.6**。

## 重要边界

插件能固定输入、流程和审计记录，但不能保证任何视频模型达到像素级一致。最终结果仍取决于模型能力、参考图质量、模型版本、采样器、动作幅度和平台内部随机机制。

外部身份识别或质量模型只通过声明式指标映射接入；插件不执行第三方 JSON 中的代码，不读取或保存 API Key。

## 安装

在 `ComfyUI/custom_nodes` 中执行：

```bash
git clone https://github.com/xinjian0101/continuity-director.git ComfyUI-ContinuityDirector
```

或将发布 ZIP 解压到：

```text
ComfyUI/custom_nodes/ComfyUI-ContinuityDirector
```

随后重启 ComfyUI。核心功能没有第三方 Python 运行依赖；视频探测、抽帧和拼接需要本机安装 FFmpeg/FFprobe。

## 推荐流程

```text
项目锁 / 演员表锁 / 场景锁
  ↓
批量导演 / Take 变体
  ↓
参考帧库 / 模型配置 / 工作流模板
  ↓
协作项目 → 编辑锁 → 审批与变更评审
  ↓
兼容矩阵 / 环境锁文件 / 生成放行门
  ↓
执行计划 / 持久队列 / 分布式调度
  ↓
生成 → 素材索引 → 技术质检 → 最佳 Take
  ↓
边界连续性 → 定向重做 → 成片拼接
  ↓
审计链 / 版本快照 / 重放比较 / 运行包
```

## v0.7 多人协作

成员角色：

```text
owner / director / editor / reviewer / operator / viewer
```

协作流程支持：

1. 对单个镜头、场景或成片获取有期限的编辑锁。
2. 通过修订号阻止旧页面覆盖新修改。
3. 提交审批、要求修改、批准、拒绝或废止版本。
4. 对 JSON 资源执行三方合并并输出具体冲突路径。
5. 使用 SHA-256 哈希链记录不可静默篡改的协作事件。
6. 只有审批、锁、环境和审计条件都通过时才开放生成。

## v0.7 分布式执行

工作节点可声明：

```json
{
  "model_profiles": ["wan", "ltxv"],
  "transports": ["local_workflow"],
  "vram_gb": 24
}
```

调度器会结合任务优先级、依赖、模型、显存、标签和剩余容量进行确定性分配。失去心跳的工作节点会被标记为 `stale`。

## 本地验证

```bash
python -m compileall -q .
python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
```

当前回归套件：**135 项测试**。

## 目录

```text
ComfyUI-ContinuityDirector/
├── continuity_core.py
├── production_core.py
├── runtime_core.py
├── orchestration_core.py
├── postprocess_core.py
├── collaboration_core.py
├── nodes.py
├── js/
├── examples/
├── tests/
├── scripts/
└── docs/
```

## 许可证

MIT。
