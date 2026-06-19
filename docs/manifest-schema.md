# Manifest Schema v1.6

Schema 1.6 兼容并自动迁移 1.0—1.5 对象。

## 核心连续性对象

| `type` | 用途 |
|---|---|
| `project_lock` | 项目画幅、帧率、视觉和种子规则 |
| `character_lock` / `cast_lock` | 人物身份、服装、道具和参考图 |
| `scene_lock` | 场景、光线、空间锚点和持久物件 |
| `shot_manifest` | 单镜提示词、种子、状态、转场和父级指纹 |
| `sequence_manifest` | 完整镜头序列 |

## 运行、质检与后期对象

包括 `workflow_template`、`run_snapshot`、`persistent_queue`、`asset_index`、`quality_gate`、`remake_plan`、`media_probe`、`technical_qc_report`、`boundary_continuity_report`、`sequence_assembly_plan`、`version_snapshot`、`rollback_plan`、`resource_quota`、`regression_baseline` 和 `artifact_lineage_graph`。

## v1.6 协作与规模化对象

| `type` | 用途 |
|---|---|
| `collaboration_manifest` | 成员、角色、权限和审批策略 |
| `edit_lock_state` | 带租约与修订号的资源编辑锁 |
| `approval_record` | 镜头、场景或成片审批状态机 |
| `change_request` | 结构化修改和评审记录 |
| `collaboration_audit_log` | SHA-256 前向哈希审计链 |
| `three_way_merge` | 基础版、我的修改和对方修改合并报告 |
| `worker_registry` | 分布式工作节点能力和心跳 |
| `distributed_schedule` | 能力与容量感知任务分配 |
| `compatibility_matrix` | 多环境兼容性报告 |
| `environment_lockfile` | Python、ComfyUI、插件、模型和硬件锁定 |
| `bulk_import_result` | CSV/JSONL 导入结果和逐行错误 |
| `template_manifest_validation` | 模板包安全结构校验 |
| `template_trust_report` | 发布者允许列表和摘要信任报告 |
| `fault_injection_plan` | 确定性 dry-run 故障场景 |
| `fault_recovery_report` | 故障恢复动作核对 |
| `replay_manifest` | 运行快照、任务种子和输出指纹 |
| `replay_comparison` | 两次运行确定性比较 |
| `generation_release_gate` | 生成前协作与治理放行结果 |
| `collaboration_dashboard` | 协作、审批、工作节点和放行汇总 |

所有可持久化对象包含 `schema_version`、`type` 和内容指纹。ZIP 包使用 SHA-256 校验文件完整性。
