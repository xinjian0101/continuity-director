from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from continuity_core import (
    ContinuityValidationError,
    SCHEMA_VERSION,
    manifest_fingerprint,
    slugify,
    stable_seed,
    validate_object,
)
from production_core import make_issue

WORKFLOW_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
TASK_STATUSES = {"queued", "leased", "running", "succeeded", "failed", "cancelled", "blocked"}
TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled"}
TASK_TRANSITIONS = {
    "queued": {"leased", "cancelled", "blocked"},
    "leased": {"running", "queued", "failed", "cancelled"},
    "running": {"succeeded", "failed", "queued", "cancelled"},
    "blocked": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "succeeded": set(),
    "cancelled": set(),
}


def _mapping(value: dict[str, Any] | str, name: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContinuityValidationError(f"{name} 不是有效 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise ContinuityValidationError(f"{name} 必须是对象")
    return deepcopy(value)


def _list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContinuityValidationError(f"{name} 不是有效 JSON 数组：{exc}") from exc
    if not isinstance(value, list):
        raise ContinuityValidationError(f"{name} 必须是数组")
    return deepcopy(value)


def _sha(value: Any, length: int = 64) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _utc_ms(now_ms: int | None = None) -> int:
    return int(now_ms if now_ms is not None else time.time() * 1000)


def validate_workflow_template(template: dict[str, Any] | str) -> dict[str, Any]:
    """Validate a declarative ComfyUI/API workflow template without executing code."""
    obj = _mapping(template, "workflow_template")
    template_id = slugify(obj.get("template_id") or obj.get("name"), "workflow-template")
    nodes = obj.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ContinuityValidationError("workflow_template.nodes 必须是非空数组")
    normalized: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    placeholders: set[str] = set()
    for index, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"nodes[{index}] 必须是对象")
        node_id = slugify(raw.get("node_id") or raw.get("id"), f"node-{index + 1}")
        if node_id in node_ids:
            raise ContinuityValidationError(f"工作流节点 ID 重复：{node_id}")
        node_ids.add(node_id)
        class_type = str(raw.get("class_type", "")).strip()
        if not class_type or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", class_type):
            raise ContinuityValidationError(f"nodes[{index}].class_type 无效")
        inputs = raw.get("inputs", {})
        if not isinstance(inputs, dict):
            raise ContinuityValidationError(f"nodes[{index}].inputs 必须是对象")
        placeholders.update(WORKFLOW_PLACEHOLDER_RE.findall(json.dumps(inputs, ensure_ascii=False)))
        normalized.append({"node_id": node_id, "class_type": class_type, "inputs": deepcopy(inputs)})
    declared = obj.get("required_fields", [])
    if isinstance(declared, str):
        declared = [item.strip() for item in declared.split(",") if item.strip()]
    if not isinstance(declared, list):
        raise ContinuityValidationError("required_fields 必须是数组")
    required_fields = sorted(set(str(item).strip() for item in declared if str(item).strip()) | placeholders)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "workflow_template",
        "template_id": template_id,
        "display_name": str(obj.get("display_name") or template_id).strip(),
        "transport": str(obj.get("transport", "comfyui_api")).strip() or "comfyui_api",
        "nodes": normalized,
        "node_count": len(normalized),
        "required_fields": required_fields,
        "metadata": deepcopy(obj.get("metadata", {})) if isinstance(obj.get("metadata", {}), dict) else {},
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def bind_workflow_template(
    template: dict[str, Any] | str,
    values: dict[str, Any] | str,
    allow_missing: bool = False,
) -> dict[str, Any]:
    """Bind typed values into a validated template using ${field} placeholders."""
    tpl = validate_workflow_template(template)
    supplied = _mapping(values, "workflow_values")
    missing = [field for field in tpl["required_fields"] if field not in supplied]
    if missing and not allow_missing:
        raise ContinuityValidationError(f"工作流缺少必填字段：{missing}")

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, str):
            return deepcopy(value)
        exact = WORKFLOW_PLACEHOLDER_RE.fullmatch(value)
        if exact:
            key = exact.group(1)
            return deepcopy(supplied.get(key, value if allow_missing else None))
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in supplied:
                return match.group(0) if allow_missing else ""
            item = supplied[key]
            if isinstance(item, (dict, list)):
                return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            return str(item)
        return WORKFLOW_PLACEHOLDER_RE.sub(replace, value)

    nodes = [{**node, "inputs": resolve(node["inputs"])} for node in tpl["nodes"]]
    unresolved = sorted(set(WORKFLOW_PLACEHOLDER_RE.findall(json.dumps(nodes, ensure_ascii=False))))
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "bound_workflow",
        "template_id": tpl["template_id"],
        "template_fingerprint": tpl["fingerprint"],
        "transport": tpl["transport"],
        "nodes": nodes,
        "node_count": len(nodes),
        "missing_fields": missing,
        "unresolved_fields": unresolved,
        "ready": not unresolved,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


SECRET_KEY_RE = re.compile(r"(?:api[_-]?key|token|secret|password|authorization)", re.IGNORECASE)


def build_run_snapshot(
    project: dict[str, Any] | str,
    sequence: dict[str, Any] | str,
    model_profile: dict[str, Any] | str,
    workflow_template: dict[str, Any] | str,
    settings: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Create a reproducible, secret-free run configuration snapshot."""
    project_obj = validate_object(project, "project_lock")
    sequence_obj = validate_object(sequence, "sequence_manifest")
    profile = _mapping(model_profile, "model_profile")
    template = validate_workflow_template(workflow_template)
    if sequence_obj.get("project_id") != project_obj.get("project_id"):
        raise ContinuityValidationError("sequence 与 project 不属于同一项目")
    raw_settings = _mapping(settings, "settings") if settings else {}
    redacted: list[str] = []

    def scrub(value: Any, path: str = "settings") -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                child = f"{path}.{key}"
                if SECRET_KEY_RE.search(str(key)):
                    result[key] = "[REDACTED]"
                    redacted.append(child)
                else:
                    result[key] = scrub(item, child)
            return result
        if isinstance(value, list):
            return [scrub(item, f"{path}[{index}]") for index, item in enumerate(value)]
        return deepcopy(value)

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "type": "run_snapshot",
        "project_id": project_obj["project_id"],
        "sequence_id": sequence_obj.get("sequence_id"),
        "project_fingerprint": manifest_fingerprint(project_obj),
        "sequence_fingerprint": manifest_fingerprint(sequence_obj),
        "model_profile": deepcopy(profile),
        "workflow_template": template,
        "settings": scrub(raw_settings),
        "redacted_paths": sorted(redacted),
    }
    snapshot["fingerprint"] = manifest_fingerprint(snapshot)
    return snapshot


def transition_task_state(
    task: dict[str, Any] | str,
    new_status: str,
    now_ms: int | None = None,
    reason: str = "",
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a strict task-state transition and append immutable history."""
    item = _mapping(task, "task")
    current = str(item.get("status", "queued")).strip().lower()
    target = str(new_status).strip().lower()
    if current not in TASK_STATUSES or target not in TASK_STATUSES:
        raise ContinuityValidationError(f"任务状态无效：{current} -> {target}")
    if target != current and target not in TASK_TRANSITIONS[current]:
        raise ContinuityValidationError(f"不允许的任务状态迁移：{current} -> {target}")
    timestamp = _utc_ms(now_ms)
    history = item.get("history", [])
    if not isinstance(history, list):
        history = []
    if target != current:
        history.append({"from": current, "to": target, "timestamp_ms": timestamp, "reason": str(reason).strip()})
    item["status"] = target
    item["updated_at_ms"] = timestamp
    item["history"] = history
    if output is not None:
        if not isinstance(output, dict):
            raise ContinuityValidationError("output 必须是对象")
        item["output"] = deepcopy(output)
    if target in TERMINAL_TASK_STATUSES:
        item["completed_at_ms"] = timestamp
        item.pop("lease", None)
    item["fingerprint"] = _sha({key: value for key, value in item.items() if key != "fingerprint"}, 32)
    return item


def create_queue_state(
    generation_queue: dict[str, Any] | str,
    run_snapshot: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Normalize a generation queue into a persistent scheduler state."""
    queue = _mapping(generation_queue, "generation_queue")
    if queue.get("type") not in {"generation_queue", "generation_task_queue"}:
        raise ContinuityValidationError("generation_queue 类型错误")
    timestamp = _utc_ms(now_ms)
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(queue.get("tasks", [])):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"tasks[{index}] 必须是对象")
        task_id = slugify(raw.get("task_id"), f"task-{index + 1}")
        if task_id in seen:
            raise ContinuityValidationError(f"任务 ID 重复：{task_id}")
        seen.add(task_id)
        item = deepcopy(raw)
        item["task_id"] = task_id
        item["status"] = str(item.get("status", "queued")).lower()
        if item["status"] not in TASK_STATUSES:
            raise ContinuityValidationError(f"任务状态无效：{item['status']}")
        item.setdefault("attempt", 1)
        item.setdefault("priority", 0)
        requirements = item.get("requires_tasks")
        if requirements is None:
            requirements = []
        if not isinstance(requirements, list):
            raise ContinuityValidationError(f"tasks[{index}].requires_tasks 必须是数组")
        item["requires_tasks"] = [slugify(value, "") for value in requirements if slugify(value, "")]
        requires_shots = item.get("requires_shots", [])
        if not isinstance(requires_shots, list):
            raise ContinuityValidationError(f"tasks[{index}].requires_shots 必须是数组")
        item["_requires_shots"] = [slugify(value, "") for value in requires_shots if slugify(value, "")]
        item["created_at_ms"] = int(item.get("created_at_ms", timestamp))
        item["updated_at_ms"] = int(item.get("updated_at_ms", timestamp))
        item.setdefault("history", [])
        item["fingerprint"] = _sha({key: value for key, value in item.items() if key != "fingerprint"}, 32)
        tasks.append(item)
    task_ids = {item["task_id"] for item in tasks}
    by_shot_take = {(item.get("shot_id"), int(item.get("take_index", 1))): item["task_id"] for item in tasks}
    by_shot: dict[str, list[str]] = {}
    for item in tasks:
        if item.get("shot_id"):
            by_shot.setdefault(str(item["shot_id"]), []).append(item["task_id"])
    for item in tasks:
        resolved = list(item.get("requires_tasks", []))
        for shot_id in item.pop("_requires_shots", []):
            matching = by_shot_take.get((shot_id, int(item.get("take_index", 1))))
            if matching:
                resolved.append(matching)
            elif by_shot.get(shot_id):
                resolved.append(sorted(by_shot[shot_id])[0])
        unknown = sorted(set(resolved) - task_ids)
        if unknown:
            raise ContinuityValidationError(f"任务 {item['task_id']} 引用了不存在的依赖：{unknown}")
        item["requires_tasks"] = sorted(set(resolved))
        item["fingerprint"] = _sha({key: value for key, value in item.items() if key != "fingerprint"}, 32)
    snapshot = _mapping(run_snapshot, "run_snapshot") if run_snapshot else None
    state = {
        "schema_version": SCHEMA_VERSION,
        "type": "persistent_queue",
        "queue_id": f"queue-{_sha([item['task_id'] for item in tasks], 16)}",
        "source_queue_fingerprint": queue.get("fingerprint") or manifest_fingerprint(queue),
        "run_snapshot_fingerprint": snapshot.get("fingerprint") if snapshot else None,
        "created_at_ms": timestamp,
        "updated_at_ms": timestamp,
        "revision": 1,
        "tasks": tasks,
        "task_count": len(tasks),
    }
    state["fingerprint"] = manifest_fingerprint(state)
    return state


def claim_ready_tasks(
    queue_state: dict[str, Any] | str,
    worker_id: str,
    limit: int = 1,
    lease_seconds: int = 300,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Lease dependency-ready tasks to one worker without duplicate claims."""
    state = _mapping(queue_state, "queue_state")
    if state.get("type") != "persistent_queue":
        raise ContinuityValidationError("queue_state 类型错误")
    wid = slugify(worker_id, "worker")
    take = max(1, min(int(limit), 128))
    lease_ms = max(1, min(int(lease_seconds), 86400)) * 1000
    timestamp = _utc_ms(now_ms)
    by_id = {task.get("task_id"): task for task in state.get("tasks", [])}
    succeeded = {task_id for task_id, task in by_id.items() if task.get("status") == "succeeded"}
    candidates: list[dict[str, Any]] = []
    for task in state.get("tasks", []):
        if task.get("status") != "queued":
            continue
        requirements = set(task.get("requires_tasks", []))
        if requirements - succeeded:
            continue
        candidates.append(task)
    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), int(item.get("created_at_ms", 0)), item.get("task_id", "")))
    claimed_ids = {item["task_id"] for item in candidates[:take]}
    updated: list[dict[str, Any]] = []
    claimed: list[dict[str, Any]] = []
    for task in state.get("tasks", []):
        if task.get("task_id") in claimed_ids:
            item = transition_task_state(task, "leased", timestamp, f"claimed by {wid}")
            item["lease"] = {"worker_id": wid, "claimed_at_ms": timestamp, "expires_at_ms": timestamp + lease_ms}
            item["fingerprint"] = _sha({key: value for key, value in item.items() if key != "fingerprint"}, 32)
            claimed.append(deepcopy(item))
            updated.append(item)
        else:
            updated.append(deepcopy(task))
    state["tasks"] = updated
    state["updated_at_ms"] = timestamp
    state["revision"] = int(state.get("revision", 0)) + 1
    state["fingerprint"] = manifest_fingerprint(state)
    return {"queue_state": state, "claimed": claimed, "claimed_count": len(claimed), "worker_id": wid}


def renew_task_leases(
    queue_state: dict[str, Any] | str,
    worker_id: str,
    task_ids: Iterable[str],
    lease_seconds: int = 300,
    now_ms: int | None = None,
) -> dict[str, Any]:
    state = _mapping(queue_state, "queue_state")
    if state.get("type") != "persistent_queue":
        raise ContinuityValidationError("queue_state 类型错误")
    wid = slugify(worker_id, "worker")
    targets = {slugify(item, "") for item in task_ids if slugify(item, "")}
    timestamp = _utc_ms(now_ms)
    extension = max(1, min(int(lease_seconds), 86400)) * 1000
    renewed: list[str] = []
    for task in state.get("tasks", []):
        lease = task.get("lease")
        if task.get("task_id") not in targets or not isinstance(lease, dict):
            continue
        if task.get("status") not in {"leased", "running"} or lease.get("worker_id") != wid:
            continue
        lease["expires_at_ms"] = timestamp + extension
        lease["renewed_at_ms"] = timestamp
        task["updated_at_ms"] = timestamp
        task["fingerprint"] = _sha({key: value for key, value in task.items() if key != "fingerprint"}, 32)
        renewed.append(task["task_id"])
    if renewed:
        state["revision"] = int(state.get("revision", 0)) + 1
        state["updated_at_ms"] = timestamp
        state["fingerprint"] = manifest_fingerprint(state)
    return {"queue_state": state, "renewed_task_ids": renewed, "renewed_count": len(renewed)}


def reap_expired_leases(
    queue_state: dict[str, Any] | str,
    now_ms: int | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    state = _mapping(queue_state, "queue_state")
    if state.get("type") != "persistent_queue":
        raise ContinuityValidationError("queue_state 类型错误")
    timestamp = _utc_ms(now_ms)
    limit = max(1, min(int(max_attempts), 100))
    requeued: list[str] = []
    failed: list[str] = []
    updated: list[dict[str, Any]] = []
    for task in state.get("tasks", []):
        lease = task.get("lease")
        expired = isinstance(lease, dict) and int(lease.get("expires_at_ms", 0)) <= timestamp
        if task.get("status") not in {"leased", "running"} or not expired:
            updated.append(deepcopy(task))
            continue
        attempt = int(task.get("attempt", 1))
        if attempt >= limit:
            item = transition_task_state(task, "failed", timestamp, "lease expired; retry limit reached")
            failed.append(item["task_id"])
        else:
            item = transition_task_state(task, "queued", timestamp, "lease expired; returned to queue")
            item["attempt"] = attempt + 1
            item.pop("lease", None)
            item.pop("completed_at_ms", None)
            item["fingerprint"] = _sha({key: value for key, value in item.items() if key != "fingerprint"}, 32)
            requeued.append(item["task_id"])
        updated.append(item)
    state["tasks"] = updated
    if requeued or failed:
        state["revision"] = int(state.get("revision", 0)) + 1
        state["updated_at_ms"] = timestamp
        state["fingerprint"] = manifest_fingerprint(state)
    return {"queue_state": state, "requeued_task_ids": requeued, "failed_task_ids": failed}


class PersistentQueueStore:
    """Atomic JSON queue store with optimistic revision checks."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, queue_id: str) -> Path:
        safe = slugify(queue_id, "queue")
        path = (self.root / f"{safe}.json").resolve()
        if self.root not in path.parents:
            raise ContinuityValidationError("队列路径越界")
        return path

    def load(self, queue_id: str) -> dict[str, Any]:
        path = self._path(queue_id)
        if not path.exists():
            raise FileNotFoundError(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ContinuityValidationError(f"队列文件损坏：{exc}") from exc
        if data.get("type") != "persistent_queue":
            raise ContinuityValidationError("队列文件类型错误")
        return data

    def save(self, queue_state: dict[str, Any] | str, expected_revision: int | None = None) -> Path:
        state = _mapping(queue_state, "queue_state")
        if state.get("type") != "persistent_queue":
            raise ContinuityValidationError("queue_state 类型错误")
        path = self._path(state.get("queue_id", "queue"))
        if expected_revision is not None and path.exists():
            current = self.load(state["queue_id"])
            if int(current.get("revision", 0)) != int(expected_revision):
                raise ContinuityValidationError("队列修订号冲突，请重新载入后再提交")
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return path

    def delete(self, queue_id: str) -> bool:
        path = self._path(queue_id)
        if not path.exists():
            return False
        path.unlink()
        return True


def build_asset_index(
    assets: list[dict[str, Any]] | str,
    project_id: str = "",
) -> dict[str, Any]:
    """Create a deduplicated index for generated video, image, audio and metadata assets."""
    items = _list(assets, "assets")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_hashes: dict[str, str] = {}
    duplicates: list[dict[str, str]] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"assets[{index}] 必须是对象")
        source = str(raw.get("source") or raw.get("path") or raw.get("url") or "").strip()
        if not source:
            raise ContinuityValidationError(f"assets[{index}].source 不能为空")
        asset_type = str(raw.get("asset_type", "video")).strip().lower()
        if asset_type not in {"video", "image", "audio", "subtitle", "metadata", "other"}:
            raise ContinuityValidationError(f"不支持的 asset_type：{asset_type}")
        digest = str(raw.get("sha256", "")).strip().lower()
        if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContinuityValidationError(f"assets[{index}].sha256 必须是 64 位十六进制")
        asset_id = slugify(raw.get("asset_id") or f"asset-{index + 1:04d}", f"asset-{index + 1:04d}")
        if asset_id in seen_ids:
            raise ContinuityValidationError(f"素材 ID 重复：{asset_id}")
        seen_ids.add(asset_id)
        if digest and digest in seen_hashes:
            duplicates.append({"asset_id": asset_id, "duplicate_of": seen_hashes[digest]})
        elif digest:
            seen_hashes[digest] = asset_id
        item = {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "source": source,
            "sha256": digest or None,
            "size_bytes": max(0, int(raw.get("size_bytes", 0))),
            "duration_seconds": max(0.0, float(raw.get("duration_seconds", 0.0))),
            "shot_id": slugify(raw.get("shot_id", ""), "") or None,
            "task_id": slugify(raw.get("task_id", ""), "") or None,
            "take_index": max(0, int(raw.get("take_index", 0))),
            "tags": sorted(set(str(tag).strip() for tag in raw.get("tags", []) if str(tag).strip())),
            "metadata": deepcopy(raw.get("metadata", {})) if isinstance(raw.get("metadata", {}), dict) else {},
        }
        item["fingerprint"] = _sha(item, 32)
        normalized.append(item)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "asset_index",
        "project_id": str(project_id).strip() or None,
        "assets": normalized,
        "asset_count": len(normalized),
        "duplicates": duplicates,
        "duplicate_count": len(duplicates),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def merge_asset_indexes(*indexes: dict[str, Any] | str) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    project_id: str | None = None
    for value in indexes:
        obj = _mapping(value, "asset_index")
        if obj.get("type") != "asset_index":
            raise ContinuityValidationError("输入必须是 asset_index")
        current_project = obj.get("project_id")
        if project_id and current_project and current_project != project_id:
            raise ContinuityValidationError("不能合并不同项目的素材索引")
        project_id = project_id or current_project
        assets.extend(obj.get("assets", []))
    by_key: dict[tuple[str | None, str], dict[str, Any]] = {}
    for asset in assets:
        key = (asset.get("sha256"), asset.get("source"))
        existing = by_key.get(key)
        if not existing:
            by_key[key] = deepcopy(asset)
        else:
            existing["tags"] = sorted(set(existing.get("tags", [])) | set(asset.get("tags", [])))
            existing["metadata"] = {**existing.get("metadata", {}), **asset.get("metadata", {})}
    return build_asset_index(list(by_key.values()), project_id or "")


QUALITY_DIMENSIONS = {
    "identity_consistency",
    "temporal_stability",
    "prompt_alignment",
    "motion_quality",
    "anatomy_quality",
    "lighting_consistency",
    "transition_match",
    "technical_quality",
}


def validate_quality_gate(profile: dict[str, Any] | str) -> dict[str, Any]:
    """Normalize weighted quality thresholds for generated takes."""
    obj = _mapping(profile, "quality_gate")
    gate_id = slugify(obj.get("gate_id") or obj.get("name"), "default-quality-gate")
    raw_dimensions = obj.get("dimensions", {})
    if not isinstance(raw_dimensions, dict) or not raw_dimensions:
        raise ContinuityValidationError("quality_gate.dimensions 必须是非空对象")
    dimensions: dict[str, dict[str, float | bool]] = {}
    total_weight = 0.0
    for name, raw in raw_dimensions.items():
        key = str(name).strip().lower()
        if key not in QUALITY_DIMENSIONS:
            raise ContinuityValidationError(f"不支持的质量维度：{key}")
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"dimensions.{key} 必须是对象")
        threshold = float(raw.get("threshold", 70.0))
        weight = float(raw.get("weight", 1.0))
        if threshold < 0 or threshold > 100:
            raise ContinuityValidationError(f"dimensions.{key}.threshold 必须在 0 到 100 之间")
        if weight < 0 or weight > 100:
            raise ContinuityValidationError(f"dimensions.{key}.weight 必须在 0 到 100 之间")
        required = bool(raw.get("required", True))
        dimensions[key] = {"threshold": round(threshold, 3), "weight": round(weight, 3), "required": required}
        total_weight += weight
    if total_weight <= 0:
        raise ContinuityValidationError("质量维度权重总和必须大于 0")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "quality_gate",
        "gate_id": gate_id,
        "dimensions": dimensions,
        "pass_score": round(float(obj.get("pass_score", 75.0)), 3),
        "warning_score": round(float(obj.get("warning_score", 60.0)), 3),
        "max_remakes": max(0, min(int(obj.get("max_remakes", 2)), 20)),
    }
    if not 0 <= result["warning_score"] <= result["pass_score"] <= 100:
        raise ContinuityValidationError("必须满足 0 <= warning_score <= pass_score <= 100")
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def evaluate_take_quality(
    quality_gate: dict[str, Any] | str,
    metrics: dict[str, Any] | str,
    task_id: str = "",
    shot_id: str = "",
    take_index: int = 0,
) -> dict[str, Any]:
    gate = validate_quality_gate(quality_gate)
    values = _mapping(metrics, "quality_metrics")
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    weighted = 0.0
    total_weight = 0.0
    hard_failure = False
    for name, config in gate["dimensions"].items():
        raw = values.get(name)
        if raw is None:
            score = 0.0
            issues.append(make_issue("QUALITY_METRIC_MISSING", "error" if config["required"] else "warning", name, "缺少质量指标", dimension=name))
        else:
            try:
                score = float(raw)
            except (TypeError, ValueError) as exc:
                raise ContinuityValidationError(f"质量指标 {name} 必须是数字") from exc
            if score < 0 or score > 100:
                raise ContinuityValidationError(f"质量指标 {name} 必须在 0 到 100 之间")
        passed = score >= float(config["threshold"])
        if config["required"] and not passed:
            hard_failure = True
            issues.append(make_issue("QUALITY_THRESHOLD_FAILED", "error", name, "质量指标低于硬性阈值", dimension=name, score=score, threshold=config["threshold"]))
        weight = float(config["weight"])
        weighted += score * weight
        total_weight += weight
        rows.append({"dimension": name, "score": round(score, 3), "threshold": config["threshold"], "weight": weight, "required": config["required"], "passed": passed})
    overall = round(weighted / total_weight, 3) if total_weight else 0.0
    if hard_failure or overall < gate["warning_score"]:
        decision = "fail"
    elif overall < gate["pass_score"]:
        decision = "warning"
    else:
        decision = "pass"
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "quality_evaluation",
        "gate_id": gate["gate_id"],
        "task_id": slugify(task_id, "") or None,
        "shot_id": slugify(shot_id, "") or None,
        "take_index": max(0, int(take_index)),
        "overall_score": overall,
        "decision": decision,
        "passed": decision == "pass",
        "dimensions": rows,
        "issues": issues,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def rank_take_results(
    evaluations: list[dict[str, Any]] | str,
    prefer_passed: bool = True,
) -> dict[str, Any]:
    items = _list(evaluations, "evaluations")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict) or raw.get("type") != "quality_evaluation":
            raise ContinuityValidationError(f"evaluations[{index}] 必须是 quality_evaluation")
        item = deepcopy(raw)
        decision_rank = {"pass": 2, "warning": 1, "fail": 0}.get(item.get("decision"), -1)
        issue_penalty = sum(8 if issue.get("severity") == "error" else 2 for issue in item.get("issues", []))
        ranking_score = float(item.get("overall_score", 0.0)) - issue_penalty
        if prefer_passed:
            ranking_score += decision_rank * 1000
        item["ranking_score"] = round(ranking_score, 3)
        normalized.append(item)
    normalized.sort(key=lambda item: (-item["ranking_score"], item.get("take_index", 0), item.get("task_id") or ""))
    for index, item in enumerate(normalized, 1):
        item["rank"] = index
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "take_ranking",
        "evaluations": normalized,
        "take_count": len(normalized),
        "best_task_id": normalized[0].get("task_id") if normalized else None,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def select_best_takes(
    evaluations: list[dict[str, Any]] | str,
    require_pass: bool = True,
) -> dict[str, Any]:
    items = _list(evaluations, "evaluations")
    groups: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("type") != "quality_evaluation":
            raise ContinuityValidationError(f"evaluations[{index}] 必须是 quality_evaluation")
        shot_id = slugify(item.get("shot_id", ""), "")
        if not shot_id:
            raise ContinuityValidationError(f"evaluations[{index}].shot_id 不能为空")
        groups.setdefault(shot_id, []).append(item)
    selections: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for shot_id in sorted(groups):
        ranking = rank_take_results(groups[shot_id], True)
        candidates = ranking["evaluations"]
        accepted = [item for item in candidates if item.get("decision") == "pass"]
        chosen = accepted[0] if accepted else (None if require_pass else (candidates[0] if candidates else None))
        if chosen is None:
            unresolved.append(shot_id)
        selections.append({
            "shot_id": shot_id,
            "selected_task_id": chosen.get("task_id") if chosen else None,
            "selected_take_index": chosen.get("take_index") if chosen else None,
            "selected_score": chosen.get("overall_score") if chosen else None,
            "decision": chosen.get("decision") if chosen else "unresolved",
            "candidate_count": len(candidates),
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "take_selection",
        "require_pass": bool(require_pass),
        "selections": selections,
        "shot_count": len(selections),
        "resolved_count": len(selections) - len(unresolved),
        "unresolved_shot_ids": unresolved,
        "complete": not unresolved,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


REMAKE_HINTS = {
    "identity_consistency": "提高身份参考图权重，优先使用 face/identity 参考，并减少大幅度侧脸变化",
    "temporal_stability": "降低运动幅度或镜头时长，增加首尾帧约束并减少复杂背景运动",
    "prompt_alignment": "精简冲突提示词，明确主体动作、镜头和场景，不要同时要求互斥行为",
    "motion_quality": "降低动作速度，拆分复杂动作，并使用更稳定的摄影机运动",
    "anatomy_quality": "减少手部遮挡与极端姿态，补充手脚解剖稳定负向约束",
    "lighting_consistency": "固定主光方向、色温和曝光，删除与场景锁冲突的光照描述",
    "transition_match": "使用上一镜尾帧作为首帧，固定人物位置、视线和运动方向",
    "technical_quality": "降低分辨率或帧数重试，检查编码、黑帧、闪烁和输出文件完整性",
}


def plan_remakes(
    evaluations: list[dict[str, Any]] | str,
    quality_gate: dict[str, Any] | str,
    previous_remakes: dict[str, int] | str | None = None,
) -> dict[str, Any]:
    items = _list(evaluations, "evaluations")
    gate = validate_quality_gate(quality_gate)
    counts = _mapping(previous_remakes, "previous_remakes") if previous_remakes else {}
    selection = select_best_takes(items, require_pass=True)
    by_shot: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_shot.setdefault(str(item.get("shot_id")), []).append(item)
    requests: list[dict[str, Any]] = []
    exhausted: list[str] = []
    for shot_id in selection["unresolved_shot_ids"]:
        used = max(0, int(counts.get(shot_id, 0)))
        if used >= gate["max_remakes"]:
            exhausted.append(shot_id)
            continue
        candidates = sorted(by_shot.get(shot_id, []), key=lambda item: -float(item.get("overall_score", 0.0)))
        best = candidates[0] if candidates else None
        failed_dimensions = []
        if best:
            failed_dimensions = [row["dimension"] for row in best.get("dimensions", []) if not row.get("passed")]
        hints = [REMAKE_HINTS[name] for name in failed_dimensions if name in REMAKE_HINTS]
        requests.append({
            "shot_id": shot_id,
            "remake_index": used + 1,
            "max_remakes": gate["max_remakes"],
            "source_task_id": best.get("task_id") if best else None,
            "failed_dimensions": failed_dimensions,
            "adjustment_hints": hints,
            "seed_strategy": "stable_variant",
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "remake_plan",
        "gate_id": gate["gate_id"],
        "requests": requests,
        "request_count": len(requests),
        "exhausted_shot_ids": exhausted,
        "complete": not requests and not exhausted,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def create_trace_log(run_id: str, metadata: dict[str, Any] | str | None = None) -> dict[str, Any]:
    meta = _mapping(metadata, "metadata") if metadata else {}
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "trace_log",
        "run_id": slugify(run_id, "run"),
        "metadata": meta,
        "events": [],
        "event_count": 0,
        "last_sequence": 0,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def append_trace_event(
    trace_log: dict[str, Any] | str,
    event_type: str,
    payload: dict[str, Any] | str | None = None,
    timestamp_ms: int | None = None,
    level: str = "info",
) -> dict[str, Any]:
    log = _mapping(trace_log, "trace_log")
    if log.get("type") != "trace_log":
        raise ContinuityValidationError("trace_log 类型错误")
    kind = slugify(event_type, "event")
    severity = str(level).strip().lower()
    if severity not in {"debug", "info", "warning", "error"}:
        raise ContinuityValidationError("trace level 必须是 debug/info/warning/error")
    data = _mapping(payload, "payload") if payload else {}
    sequence = int(log.get("last_sequence", 0)) + 1
    event = {
        "event_id": f"evt-{sequence:06d}-{_sha([kind, data], 8)}",
        "sequence": sequence,
        "timestamp_ms": _utc_ms(timestamp_ms),
        "event_type": kind,
        "level": severity,
        "payload": data,
    }
    event["fingerprint"] = _sha(event, 32)
    log.setdefault("events", []).append(event)
    log["event_count"] = len(log["events"])
    log["last_sequence"] = sequence
    log["fingerprint"] = manifest_fingerprint(log)
    return log


def summarize_trace_log(trace_log: dict[str, Any] | str) -> dict[str, Any]:
    log = _mapping(trace_log, "trace_log")
    if log.get("type") != "trace_log":
        raise ContinuityValidationError("trace_log 类型错误")
    by_type: dict[str, int] = {}
    by_level = {"debug": 0, "info": 0, "warning": 0, "error": 0}
    first_ms = None
    last_ms = None
    for event in log.get("events", []):
        by_type[event.get("event_type", "event")] = by_type.get(event.get("event_type", "event"), 0) + 1
        level = event.get("level", "info")
        by_level[level] = by_level.get(level, 0) + 1
        timestamp = int(event.get("timestamp_ms", 0))
        first_ms = timestamp if first_ms is None else min(first_ms, timestamp)
        last_ms = timestamp if last_ms is None else max(last_ms, timestamp)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "trace_summary",
        "run_id": log.get("run_id"),
        "event_count": len(log.get("events", [])),
        "events_by_type": dict(sorted(by_type.items())),
        "events_by_level": by_level,
        "first_timestamp_ms": first_ms,
        "last_timestamp_ms": last_ms,
        "duration_ms": (last_ms - first_ms) if first_ms is not None and last_ms is not None else 0,
        "has_errors": by_level.get("error", 0) > 0,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def package_run_bundle(
    path: str | os.PathLike[str],
    run_snapshot: dict[str, Any] | str,
    queue_state: dict[str, Any] | str,
    quality_gate: dict[str, Any] | str | None = None,
    asset_index: dict[str, Any] | str | None = None,
    trace_log: dict[str, Any] | str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a portable, checksummed ZIP containing all data needed to resume a run."""
    snapshot = _mapping(run_snapshot, "run_snapshot")
    queue = _mapping(queue_state, "queue_state")
    if snapshot.get("type") != "run_snapshot" or queue.get("type") != "persistent_queue":
        raise ContinuityValidationError("run_snapshot 或 queue_state 类型错误")
    files: dict[str, bytes] = {
        "run_snapshot.json": json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        "queue_state.json": json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
    }
    optional = {
        "quality_gate.json": (_mapping(quality_gate, "quality_gate") if quality_gate else None),
        "asset_index.json": (_mapping(asset_index, "asset_index") if asset_index else None),
        "trace_log.json": (_mapping(trace_log, "trace_log") if trace_log else None),
    }
    for name, value in optional.items():
        if value is not None:
            files[name] = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    checksums = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}
    bundle_manifest = {
        "schema_version": SCHEMA_VERSION,
        "type": "run_bundle",
        "run_snapshot_fingerprint": snapshot.get("fingerprint"),
        "queue_id": queue.get("queue_id"),
        "files": sorted(files),
        "checksums": checksums,
    }
    files["bundle_manifest.json"] = json.dumps(bundle_manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        stem, suffix = target.stem, target.suffix
        counter = 2
        while target.exists():
            target = target.with_name(f"{stem}-{counter}{suffix}")
            counter += 1
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                archive.writestr(name, content)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return target


def verify_run_bundle(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    issues: list[dict[str, Any]] = []
    checked = 0
    if not source.is_file():
        return {"schema_version": SCHEMA_VERSION, "type": "run_bundle_verification", "valid": False, "checked_files": 0, "issues": [make_issue("BUNDLE_NOT_FOUND", "error", "path", "运行包不存在")]}
    try:
        with zipfile.ZipFile(source, "r") as archive:
            names = archive.namelist()
            unsafe = [name for name in names if name.startswith(("/", "\\")) or ".." in Path(name).parts]
            if unsafe:
                issues.append(make_issue("UNSAFE_BUNDLE_PATH", "error", "archive", "运行包包含危险路径", paths=unsafe))
            if len(names) != len(set(names)):
                issues.append(make_issue("DUPLICATE_BUNDLE_ENTRY", "error", "archive", "运行包包含重复文件名"))
            if "bundle_manifest.json" not in names:
                issues.append(make_issue("BUNDLE_MANIFEST_MISSING", "error", "bundle_manifest.json", "运行包缺少清单"))
            else:
                manifest = json.loads(archive.read("bundle_manifest.json").decode("utf-8"))
                for name, expected in manifest.get("checksums", {}).items():
                    if name not in names:
                        issues.append(make_issue("BUNDLE_FILE_MISSING", "error", name, "运行包文件缺失"))
                        continue
                    actual = hashlib.sha256(archive.read(name)).hexdigest()
                    checked += 1
                    if actual != expected:
                        issues.append(make_issue("BUNDLE_CHECKSUM_MISMATCH", "error", name, "运行包文件校验失败", expected=expected, actual=actual))
                for required in ("run_snapshot.json", "queue_state.json"):
                    if required not in names:
                        issues.append(make_issue("BUNDLE_REQUIRED_FILE_MISSING", "error", required, "运行包缺少必需文件"))
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        issues.append(make_issue("BUNDLE_CORRUPT", "error", "archive", "运行包损坏或清单无效", error=str(exc)))
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "run_bundle_verification",
        "path": str(source),
        "valid": not any(item.get("severity") == "error" for item in issues),
        "checked_files": checked,
        "issues": issues,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result
