from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any, Iterable

from continuity_core import (
    ContinuityValidationError,
    SCHEMA_VERSION,
    manifest_fingerprint,
    provider_payload,
    slugify,
    stable_seed,
    validate_object,
)
from production_core import make_issue

REFERENCE_ROLES = {
    "identity", "face", "wardrobe", "pose", "style", "environment",
    "first_frame", "last_frame", "prop", "location",
}
REFERENCE_STATUSES = {"candidate", "approved", "rejected", "retired"}


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


def _sha(value: Any, length: int = 24) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def build_reference_registry(
    project: dict[str, Any] | str,
    frames: list[dict[str, Any]] | str,
) -> dict[str, Any]:
    """Create an immutable registry for identity, scene and transition reference frames."""
    project_obj = validate_object(project, "project_lock")
    items = _list(frames, "frames")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"frames[{index}] 必须是对象")
        source = str(raw.get("source", "")).strip()
        if not source:
            raise ContinuityValidationError(f"frames[{index}].source 不能为空")
        role = str(raw.get("role", "identity")).strip().lower()
        if role not in REFERENCE_ROLES:
            raise ContinuityValidationError(f"frames[{index}].role 不受支持：{role}")
        status = str(raw.get("status", "candidate")).strip().lower()
        if status not in REFERENCE_STATUSES:
            raise ContinuityValidationError(f"frames[{index}].status 不受支持：{status}")
        frame_id = slugify(raw.get("frame_id") or f"ref-{index + 1:03d}", f"ref-{index + 1:03d}")
        if frame_id in seen:
            raise ContinuityValidationError(f"参考帧 ID 重复：{frame_id}")
        seen.add(frame_id)
        item = {
            "frame_id": frame_id,
            "source": source,
            "role": role,
            "status": status,
            "weight": round(max(0.0, min(float(raw.get("weight", 1.0)), 2.0)), 3),
            "character_id": slugify(raw.get("character_id", ""), "") or None,
            "scene_id": slugify(raw.get("scene_id", ""), "") or None,
            "shot_id": slugify(raw.get("shot_id", ""), "") or None,
            "frame_index": max(0, int(raw.get("frame_index", 0))),
            "created_from": str(raw.get("created_from", "manual")).strip() or "manual",
            "notes": str(raw.get("notes", "")).strip(),
        }
        item["fingerprint"] = _sha(item)
        normalized.append(item)
    registry = {
        "schema_version": SCHEMA_VERSION,
        "type": "reference_registry",
        "project_id": project_obj["project_id"],
        "frame_count": len(normalized),
        "frames": normalized,
    }
    registry["fingerprint"] = manifest_fingerprint(registry)
    return registry


def update_reference_status(
    registry: dict[str, Any] | str,
    frame_id: str,
    status: str,
    notes: str = "",
) -> dict[str, Any]:
    obj = _mapping(registry, "registry")
    if obj.get("type") != "reference_registry":
        raise ContinuityValidationError("registry 必须是 reference_registry")
    target = slugify(frame_id, "")
    new_status = str(status).strip().lower()
    if new_status not in REFERENCE_STATUSES:
        raise ContinuityValidationError(f"不支持的参考帧状态：{new_status}")
    changed = False
    for item in obj.get("frames", []):
        if item.get("frame_id") == target:
            item["status"] = new_status
            if notes:
                item["notes"] = str(notes).strip()
            item["fingerprint"] = _sha({k: v for k, v in item.items() if k != "fingerprint"})
            changed = True
            break
    if not changed:
        raise ContinuityValidationError(f"不存在参考帧：{target}")
    obj["fingerprint"] = manifest_fingerprint(obj)
    return obj


def plan_character_presence(
    cast: dict[str, Any] | str,
    sequence: dict[str, Any] | str,
    presence_plan: list[dict[str, Any]] | str,
) -> dict[str, Any]:
    """Validate who is on screen, who enters and who exits for every shot."""
    cast_obj = _mapping(cast, "cast")
    sequence_obj = validate_object(sequence, "sequence_manifest")
    if cast_obj.get("type") != "cast_lock":
        raise ContinuityValidationError("cast 必须是 cast_lock")
    if cast_obj.get("project_id") != sequence_obj.get("project_id"):
        raise ContinuityValidationError("cast 与 sequence 不属于同一项目")
    known = {item.get("character_id") for item in cast_obj.get("characters", [])}
    shot_ids = [item.get("shot", {}).get("shot_id") for item in sequence_obj.get("shots", [])]
    supplied = _list(presence_plan, "presence_plan")
    by_shot: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(supplied):
        if not isinstance(raw, dict):
            issues.append(make_issue("PRESENCE_ITEM_TYPE", "error", f"presence_plan[{index}]", "出入场计划必须是对象"))
            continue
        shot_id = slugify(raw.get("shot_id", ""), "")
        if shot_id not in shot_ids:
            issues.append(make_issue("UNKNOWN_PRESENCE_SHOT", "error", f"presence_plan[{index}].shot_id", "出入场计划引用了不存在的镜头", value=shot_id))
            continue
        if shot_id in by_shot:
            issues.append(make_issue("DUPLICATE_PRESENCE_SHOT", "error", f"presence_plan[{index}].shot_id", "同一镜头存在重复出入场计划", value=shot_id))
            continue
        def ids(field: str) -> list[str]:
            values = raw.get(field, [])
            if isinstance(values, str):
                values = [part.strip() for part in values.split(",") if part.strip()]
            return [slugify(value, "") for value in values if slugify(value, "")]
        item = {
            "shot_id": shot_id,
            "present": ids("present"),
            "entrances": ids("entrances"),
            "exits": ids("exits"),
            "offscreen": ids("offscreen"),
        }
        for field in ("present", "entrances", "exits", "offscreen"):
            unknown = sorted(set(item[field]) - known)
            for character_id in unknown:
                issues.append(make_issue("UNKNOWN_PRESENCE_CHARACTER", "error", f"{shot_id}.{field}", "出入场计划引用了演员表之外的角色", character_id=character_id))
        by_shot[shot_id] = item

    active: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for shot_id in shot_ids:
        item = by_shot.get(shot_id, {"shot_id": shot_id, "present": sorted(active), "entrances": [], "exits": [], "offscreen": []})
        entrances = set(item["entrances"])
        exits = set(item["exits"])
        expected = (active | entrances) - exits
        declared = set(item["present"])
        if entrances & active:
            issues.append(make_issue("DUPLICATE_ENTRANCE", "warning", f"{shot_id}.entrances", "角色已在场却再次入场", characters=sorted(entrances & active)))
        if exits - (active | entrances):
            issues.append(make_issue("EXIT_WHILE_ABSENT", "error", f"{shot_id}.exits", "角色未在场却被安排退场", characters=sorted(exits - (active | entrances))))
        if declared != expected:
            issues.append(make_issue("PRESENCE_STATE_MISMATCH", "warning", f"{shot_id}.present", "声明的在场角色与出入场推导结果不同", declared=sorted(declared), expected=sorted(expected)))
            declared = expected
        active = set(declared)
        item["present"] = sorted(declared)
        normalized.append(item)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "presence_plan",
        "project_id": sequence_obj.get("project_id"),
        "sequence_id": sequence_obj.get("sequence_id"),
        "shots": normalized,
        "issues": issues,
        "valid": not any(item["severity"] == "error" for item in issues),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def _parse_timecode(value: str, fps: int) -> int:
    text = str(value or "00:00:00:00").strip()
    match = re.fullmatch(r"(\d{1,3}):(\d{2}):(\d{2}):(\d{2})", text)
    if not match:
        raise ContinuityValidationError("timecode 必须使用 HH:MM:SS:FF 格式")
    hours, minutes, seconds, frames = map(int, match.groups())
    if minutes >= 60 or seconds >= 60 or frames >= fps:
        raise ContinuityValidationError("timecode 数值超出有效范围")
    return (((hours * 60) + minutes) * 60 + seconds) * fps + frames


def _format_timecode(frame: int, fps: int) -> str:
    frame = max(0, int(frame))
    ff = frame % fps
    total_seconds = frame // fps
    ss = total_seconds % 60
    total_minutes = total_seconds // 60
    mm = total_minutes % 60
    hh = total_minutes // 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def build_sequence_timeline(
    sequence: dict[str, Any] | str,
    start_timecode: str = "00:00:00:00",
    handle_frames: int = 0,
) -> dict[str, Any]:
    """Build exact frame/timecode boundaries and detect story-time regressions."""
    obj = validate_object(sequence, "sequence_manifest")
    shots = obj.get("shots", [])
    fps = int(shots[0].get("project", {}).get("fps", 24)) if shots else 24
    if fps < 1:
        raise ContinuityValidationError("fps 必须大于 0")
    handles = max(0, int(handle_frames))
    cursor = _parse_timecode(start_timecode, fps)
    timeline: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    previous_story_time: float | None = None
    for index, shot in enumerate(shots, start=1):
        duration = float(shot.get("shot", {}).get("duration_seconds", 0.0))
        frame_count = max(1, int(round(duration * fps)))
        start_frame = cursor
        end_frame_exclusive = start_frame + frame_count
        custom = shot.get("continuity_state", {}).get("custom", {})
        story_time = custom.get("story_time_seconds")
        if story_time is not None:
            try:
                story_time = float(story_time)
                if previous_story_time is not None and story_time < previous_story_time:
                    issues.append(make_issue("STORY_TIME_REGRESSION", "warning", f"shots[{index - 1}].continuity_state.custom.story_time_seconds", "故事时间发生倒退", before=previous_story_time, after=story_time))
                previous_story_time = story_time
            except (TypeError, ValueError):
                issues.append(make_issue("INVALID_STORY_TIME", "error", f"shots[{index - 1}].continuity_state.custom.story_time_seconds", "story_time_seconds 必须是数字"))
                story_time = None
        timeline.append({
            "shot_id": shot.get("shot", {}).get("shot_id"),
            "sequence_index": index,
            "start_frame": start_frame,
            "end_frame_exclusive": end_frame_exclusive,
            "frame_count": frame_count,
            "start_timecode": _format_timecode(start_frame, fps),
            "end_timecode_exclusive": _format_timecode(end_frame_exclusive, fps),
            "source_in_frame": handles,
            "source_out_frame_exclusive": handles + frame_count,
            "story_time_seconds": story_time,
        })
        cursor = end_frame_exclusive
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "sequence_timeline",
        "project_id": obj.get("project_id"),
        "sequence_id": obj.get("sequence_id"),
        "fps": fps,
        "start_timecode": start_timecode,
        "handle_frames": handles,
        "total_frames": max(0, cursor - _parse_timecode(start_timecode, fps)),
        "total_duration_seconds": round(max(0, cursor - _parse_timecode(start_timecode, fps)) / fps, 3),
        "shots": timeline,
        "issues": issues,
        "valid": not any(item["severity"] == "error" for item in issues),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def compile_dependency_graph(
    sequence: dict[str, Any] | str,
    extra_dependencies: list[dict[str, Any]] | str | None = None,
) -> dict[str, Any]:
    """Compile shot dependencies into a validated DAG."""
    obj = validate_object(sequence, "sequence_manifest")
    shot_ids = [shot.get("shot", {}).get("shot_id") for shot in obj.get("shots", [])]
    if any(not item for item in shot_ids) or len(set(shot_ids)) != len(shot_ids):
        raise ContinuityValidationError("序列镜头 ID 缺失或重复，无法建立依赖图")
    dependencies: dict[str, set[str]] = {shot_id: set() for shot_id in shot_ids}
    for index, shot in enumerate(obj.get("shots", [])):
        shot_id = shot_ids[index]
        previous_id = shot.get("previous_shot_id")
        if previous_id in dependencies:
            dependencies[shot_id].add(previous_id)
        elif index > 0:
            dependencies[shot_id].add(shot_ids[index - 1])
    for index, raw in enumerate(_list(extra_dependencies, "extra_dependencies")):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"extra_dependencies[{index}] 必须是对象")
        shot_id = slugify(raw.get("shot_id", ""), "")
        requires = raw.get("requires", [])
        if isinstance(requires, str):
            requires = [part.strip() for part in requires.split(",") if part.strip()]
        requires = [slugify(item, "") for item in requires]
        if shot_id not in dependencies:
            raise ContinuityValidationError(f"依赖图引用了不存在的镜头：{shot_id}")
        unknown = set(requires) - set(shot_ids)
        if unknown:
            raise ContinuityValidationError(f"镜头 {shot_id} 依赖不存在的镜头：{sorted(unknown)}")
        if shot_id in requires:
            raise ContinuityValidationError(f"镜头 {shot_id} 不能依赖自身")
        dependencies[shot_id].update(requires)

    indegree = {node: len(reqs) for node, reqs in dependencies.items()}
    reverse: dict[str, set[str]] = {node: set() for node in dependencies}
    for node, reqs in dependencies.items():
        for req in reqs:
            reverse[req].add(node)
    queue = [node for node in shot_ids if indegree[node] == 0]
    topological: list[str] = []
    while queue:
        node = queue.pop(0)
        topological.append(node)
        for child in sorted(reverse[node], key=shot_ids.index):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    issues: list[dict[str, Any]] = []
    if len(topological) != len(shot_ids):
        cycle_nodes = [node for node in shot_ids if indegree[node] > 0]
        issues.append(make_issue("DEPENDENCY_CYCLE", "error", "dependencies", "镜头依赖形成循环", nodes=cycle_nodes))
    graph = {
        "schema_version": SCHEMA_VERSION,
        "type": "shot_dependency_graph",
        "project_id": obj.get("project_id"),
        "sequence_id": obj.get("sequence_id"),
        "nodes": shot_ids,
        "dependencies": {node: sorted(reqs, key=shot_ids.index) for node, reqs in dependencies.items()},
        "topological_order": topological,
        "issues": issues,
        "valid": not issues,
    }
    graph["fingerprint"] = manifest_fingerprint(graph)
    return graph


def schedule_execution_waves(
    dependency_graph: dict[str, Any] | str,
    max_parallel: int = 4,
) -> dict[str, Any]:
    """Turn a DAG into deterministic parallel execution waves."""
    graph = _mapping(dependency_graph, "dependency_graph")
    if graph.get("type") != "shot_dependency_graph":
        raise ContinuityValidationError("dependency_graph 必须是 shot_dependency_graph")
    if not graph.get("valid", False):
        raise ContinuityValidationError("依赖图无效，不能生成并行调度")
    limit = max(1, min(int(max_parallel), 64))
    nodes = list(graph.get("nodes", []))
    dependencies = {node: set(graph.get("dependencies", {}).get(node, [])) for node in nodes}
    remaining = set(nodes)
    completed: set[str] = set()
    waves: list[dict[str, Any]] = []
    while remaining:
        ready = [node for node in nodes if node in remaining and dependencies[node] <= completed]
        if not ready:
            raise ContinuityValidationError("依赖图无法继续调度，可能存在循环")
        for offset in range(0, len(ready), limit):
            batch = ready[offset: offset + limit]
            waves.append({
                "wave_index": len(waves) + 1,
                "shot_ids": batch,
                "parallel_count": len(batch),
                "requires_completed": sorted(set().union(*(dependencies[node] for node in batch)) if batch else set(), key=nodes.index),
            })
            completed.update(batch)
            remaining.difference_update(batch)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "type": "execution_waves",
        "project_id": graph.get("project_id"),
        "sequence_id": graph.get("sequence_id"),
        "max_parallel": limit,
        "wave_count": len(waves),
        "waves": waves,
    }
    plan["fingerprint"] = manifest_fingerprint(plan)
    return plan


RETRY_SEED_STRATEGIES = {"same", "increment", "stable_variant"}


def build_retry_policy(
    max_attempts: int = 3,
    seed_strategy: str = "stable_variant",
    backoff_seconds: Iterable[float] = (0, 2, 5),
    retryable_codes: Iterable[str] = ("timeout", "rate_limit", "provider_error", "oom"),
) -> dict[str, Any]:
    attempts = max(1, min(int(max_attempts), 10))
    strategy = str(seed_strategy).strip().lower()
    if strategy not in RETRY_SEED_STRATEGIES:
        raise ContinuityValidationError(f"不支持的重试种子策略：{strategy}")
    backoff = [max(0.0, float(item)) for item in backoff_seconds]
    if not backoff:
        backoff = [0.0]
    while len(backoff) < attempts:
        backoff.append(backoff[-1])
    policy = {
        "schema_version": SCHEMA_VERSION,
        "type": "retry_policy",
        "max_attempts": attempts,
        "seed_strategy": strategy,
        "backoff_seconds": backoff[:attempts],
        "retryable_codes": sorted({str(item).strip().lower() for item in retryable_codes if str(item).strip()}),
    }
    policy["fingerprint"] = manifest_fingerprint(policy)
    return policy


def derive_retry_attempt(
    manifest: dict[str, Any] | str,
    attempt: int,
    policy: dict[str, Any] | str,
) -> dict[str, Any]:
    shot = validate_object(manifest, "shot_manifest")
    policy_obj = _mapping(policy, "policy")
    if policy_obj.get("type") != "retry_policy":
        raise ContinuityValidationError("policy 必须是 retry_policy")
    number = int(attempt)
    if number < 1 or number > int(policy_obj.get("max_attempts", 1)):
        raise ContinuityValidationError("attempt 超出 retry_policy 范围")
    base_seed = int(shot.get("seed", 0))
    strategy = policy_obj.get("seed_strategy")
    if strategy == "same":
        seed = base_seed
    elif strategy == "increment":
        seed = (base_seed + number - 1) % (2**63 - 1)
    else:
        seed = stable_seed(base_seed, shot.get("shot", {}).get("shot_id"), f"retry-{number}")
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "retry_attempt",
        "shot_id": shot.get("shot", {}).get("shot_id"),
        "attempt": number,
        "seed": seed,
        "backoff_seconds": policy_obj.get("backoff_seconds", [0])[number - 1],
        "manifest_fingerprint": shot.get("fingerprint") or manifest_fingerprint(shot),
        "policy_fingerprint": policy_obj.get("fingerprint"),
    }


def compile_task_queue(
    sequence: dict[str, Any] | str,
    provider: str = "generic",
    model_profile: dict[str, Any] | str | None = None,
    dependency_graph: dict[str, Any] | str | None = None,
    take_count: int = 1,
) -> dict[str, Any]:
    """Compile portable generation tasks without executing external services."""
    obj = validate_object(sequence, "sequence_manifest")
    graph = _mapping(dependency_graph, "dependency_graph") if dependency_graph else compile_dependency_graph(obj)
    if not graph.get("valid"):
        raise ContinuityValidationError("依赖图无效，不能编译任务队列")
    profile = _mapping(model_profile, "model_profile") if model_profile else None
    count = max(1, min(int(take_count), 16))
    shots = {shot.get("shot", {}).get("shot_id"): shot for shot in obj.get("shots", [])}
    tasks: list[dict[str, Any]] = []
    for shot_id in graph.get("topological_order", []):
        shot = shots[shot_id]
        for take_index in range(1, count + 1):
            task_id = slugify(f"{shot_id}-take-{take_index:02d}", f"task-{len(tasks)+1:04d}")
            payload = provider_payload(shot, provider)
            if profile:
                payload["model_profile_id"] = profile.get("profile_id") or profile.get("name")
            task = {
                "task_id": task_id,
                "shot_id": shot_id,
                "take_index": take_index,
                "status": "queued",
                "requires_shots": list(graph.get("dependencies", {}).get(shot_id, [])),
                "manifest_fingerprint": shot.get("fingerprint") or manifest_fingerprint(shot),
                "seed": stable_seed(shot.get("seed", 0), shot_id, f"queue-take-{take_index}"),
                "provider": provider,
                "payload": payload,
            }
            task["fingerprint"] = _sha(task)
            tasks.append(task)
    queue = {
        "schema_version": SCHEMA_VERSION,
        "type": "generation_task_queue",
        "project_id": obj.get("project_id"),
        "sequence_id": obj.get("sequence_id"),
        "provider": provider,
        "task_count": len(tasks),
        "take_count": count,
        "tasks": tasks,
    }
    queue["fingerprint"] = manifest_fingerprint(queue)
    return queue


TASK_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled", "skipped"}


def reconcile_task_results(
    queue: dict[str, Any] | str,
    results: list[dict[str, Any]] | str,
) -> dict[str, Any]:
    obj = _mapping(queue, "queue")
    if obj.get("type") != "generation_task_queue":
        raise ContinuityValidationError("queue 必须是 generation_task_queue")
    supplied = _list(results, "results")
    task_map = {task.get("task_id"): deepcopy(task) for task in obj.get("tasks", [])}
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, result in enumerate(supplied):
        if not isinstance(result, dict):
            issues.append(make_issue("RESULT_TYPE", "error", f"results[{index}]", "任务结果必须是对象"))
            continue
        task_id = slugify(result.get("task_id", ""), "")
        if task_id not in task_map:
            issues.append(make_issue("UNKNOWN_RESULT_TASK", "error", f"results[{index}].task_id", "结果引用了不存在的任务", task_id=task_id))
            continue
        if task_id in seen:
            issues.append(make_issue("DUPLICATE_RESULT", "warning", f"results[{index}].task_id", "同一任务返回了多个结果，采用最后一个", task_id=task_id))
        seen.add(task_id)
        status = str(result.get("status", "failed")).strip().lower()
        if status not in TASK_STATUSES:
            issues.append(make_issue("INVALID_TASK_STATUS", "error", f"results[{index}].status", "任务状态不受支持", status=status))
            continue
        task_map[task_id].update({
            "status": status,
            "output": deepcopy(result.get("output")),
            "error": deepcopy(result.get("error")),
            "attempt": max(1, int(result.get("attempt", 1))),
            "duration_seconds": max(0.0, float(result.get("duration_seconds", 0.0))),
        })
    tasks = [task_map[task.get("task_id")] for task in obj.get("tasks", [])]
    counts = {status: sum(1 for task in tasks if task.get("status") == status) for status in sorted(TASK_STATUSES)}
    by_shot: dict[str, dict[str, Any]] = {}
    for task in tasks:
        summary = by_shot.setdefault(task.get("shot_id"), {"succeeded": 0, "failed": 0, "pending": 0, "best_task_id": None})
        status = task.get("status")
        if status == "succeeded":
            summary["succeeded"] += 1
            summary["best_task_id"] = summary["best_task_id"] or task.get("task_id")
        elif status == "failed":
            summary["failed"] += 1
        else:
            summary["pending"] += 1
    report = {
        "schema_version": SCHEMA_VERSION,
        "type": "task_reconciliation",
        "queue_fingerprint": obj.get("fingerprint"),
        "tasks": tasks,
        "counts": counts,
        "shots": by_shot,
        "issues": issues,
        "complete": counts.get("queued", 0) + counts.get("running", 0) == 0,
        "valid": not any(item["severity"] == "error" for item in issues),
    }
    report["fingerprint"] = manifest_fingerprint(report)
    return report


FAILURE_PATTERNS = (
    ("rate_limit", ("rate limit", "429", "too many requests"), True, "延迟后重试并降低并发"),
    ("timeout", ("timeout", "timed out", "deadline exceeded"), True, "保持输入不变并重试"),
    ("oom", ("out of memory", "cuda oom", "allocation failed"), True, "降低分辨率、帧数或批量大小"),
    ("content_policy", ("content policy", "safety filter", "moderation"), False, "修改违规内容后重新提交"),
    ("invalid_input", ("invalid input", "validation", "bad request", "400"), False, "修正参数或平台不支持的字段"),
    ("provider_error", ("internal server error", "service unavailable", "502", "503"), True, "使用同一种子重试或切换备用平台"),
)


def classify_generation_failure(error: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(error, dict):
        code = str(error.get("code", "")).strip().lower()
        message = str(error.get("message", "")).strip()
    else:
        code = ""
        message = str(error).strip()
    haystack = f"{code} {message}".lower()
    category = "unknown"
    retryable = False
    action = "人工检查原始错误和输入参数"
    for name, patterns, can_retry, recovery in FAILURE_PATTERNS:
        if code == name or any(pattern in haystack for pattern in patterns):
            category, retryable, action = name, can_retry, recovery
            break
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "failure_classification",
        "category": category,
        "retryable": retryable,
        "recommended_action": action,
        "original_code": code or None,
        "message": message,
        "fingerprint": _sha({"code": code, "message": message, "category": category}),
    }


MODEL_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "local-general-video": {
        "display_name": "Local General Video",
        "transport": "local_workflow",
        "supports_seed": True,
        "supports_identity_reference": True,
        "supports_first_frame": True,
        "supports_last_frame": False,
        "supports_negative_prompt": True,
        "max_reference_images": 4,
        "max_duration_seconds": 10.0,
        "supported_fps": [16, 24, 25, 30],
        "base_cost_per_task": 0.0,
        "cost_per_second": 0.0,
    },
    "local-first-last-frame": {
        "display_name": "Local First/Last Frame Video",
        "transport": "local_workflow",
        "supports_seed": True,
        "supports_identity_reference": True,
        "supports_first_frame": True,
        "supports_last_frame": True,
        "supports_negative_prompt": True,
        "max_reference_images": 6,
        "max_duration_seconds": 12.0,
        "supported_fps": [16, 24, 30],
        "base_cost_per_task": 0.0,
        "cost_per_second": 0.0,
    },
    "cloud-image-video": {
        "display_name": "Cloud Image-to-Video",
        "transport": "external_service",
        "supports_seed": False,
        "supports_identity_reference": True,
        "supports_first_frame": True,
        "supports_last_frame": False,
        "supports_negative_prompt": False,
        "max_reference_images": 1,
        "max_duration_seconds": 10.0,
        "supported_fps": [],
        "base_cost_per_task": 0.0,
        "cost_per_second": 0.0,
    },
}


def validate_model_profile(profile: dict[str, Any] | str) -> dict[str, Any]:
    raw = _mapping(profile, "model_profile")
    profile_id = slugify(raw.get("profile_id") or raw.get("name"), "model-profile")
    transport = str(raw.get("transport", "local_workflow")).strip().lower()
    if transport not in {"local_workflow", "external_service", "manual_export"}:
        raise ContinuityValidationError(f"不支持的模型 transport：{transport}")
    fps_values = raw.get("supported_fps", [])
    if not isinstance(fps_values, list):
        raise ContinuityValidationError("supported_fps 必须是数组")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "model_profile",
        "profile_id": profile_id,
        "display_name": str(raw.get("display_name", profile_id)).strip() or profile_id,
        "transport": transport,
        "supports_seed": bool(raw.get("supports_seed", False)),
        "supports_identity_reference": bool(raw.get("supports_identity_reference", False)),
        "supports_first_frame": bool(raw.get("supports_first_frame", False)),
        "supports_last_frame": bool(raw.get("supports_last_frame", False)),
        "supports_negative_prompt": bool(raw.get("supports_negative_prompt", False)),
        "max_reference_images": max(0, min(int(raw.get("max_reference_images", 0)), 32)),
        "max_duration_seconds": max(0.1, min(float(raw.get("max_duration_seconds", 10.0)), 600.0)),
        "supported_fps": sorted({int(item) for item in fps_values if 1 <= int(item) <= 240}),
        "base_cost_per_task": max(0.0, float(raw.get("base_cost_per_task", 0.0))),
        "cost_per_second": max(0.0, float(raw.get("cost_per_second", 0.0))),
        "resolution_multipliers": deepcopy(raw.get("resolution_multipliers", {})) if isinstance(raw.get("resolution_multipliers", {}), dict) else {},
        "prompt_template": str(raw.get("prompt_template", "{positive_prompt}")).strip() or "{positive_prompt}",
        "negative_template": str(raw.get("negative_template", "{negative_prompt}")).strip() or "{negative_prompt}",
        "extra": deepcopy(raw.get("extra", {})) if isinstance(raw.get("extra", {}), dict) else {},
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def model_profile_registry(custom_profiles: list[dict[str, Any]] | str | None = None) -> dict[str, Any]:
    profiles = [validate_model_profile({"profile_id": key, **value}) for key, value in MODEL_PROFILE_PRESETS.items()]
    seen = {item["profile_id"] for item in profiles}
    for index, raw in enumerate(_list(custom_profiles, "custom_profiles")):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"custom_profiles[{index}] 必须是对象")
        profile = validate_model_profile(raw)
        if profile["profile_id"] in seen:
            profiles = [item for item in profiles if item["profile_id"] != profile["profile_id"]]
        profiles.append(profile)
        seen.add(profile["profile_id"])
    registry = {"schema_version": SCHEMA_VERSION, "type": "model_profile_registry", "profiles": profiles, "profile_count": len(profiles)}
    registry["fingerprint"] = manifest_fingerprint(registry)
    return registry


def match_sequence_to_model(
    sequence: dict[str, Any] | str,
    model_profile: dict[str, Any] | str,
    reference_registry: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    obj = validate_object(sequence, "sequence_manifest")
    profile = validate_model_profile(model_profile)
    registry = _mapping(reference_registry, "reference_registry") if reference_registry else None
    issues: list[dict[str, Any]] = []
    shots: list[dict[str, Any]] = []
    approved_refs = []
    if registry:
        if registry.get("type") != "reference_registry":
            raise ContinuityValidationError("reference_registry 类型错误")
        approved_refs = [item for item in registry.get("frames", []) if item.get("status") == "approved"]
    for index, shot in enumerate(obj.get("shots", [])):
        shot_id = shot.get("shot", {}).get("shot_id")
        duration = float(shot.get("shot", {}).get("duration_seconds", 0.0))
        fps = int(shot.get("project", {}).get("fps", 24))
        shot_issues: list[dict[str, Any]] = []
        if duration > profile["max_duration_seconds"]:
            shot_issues.append(make_issue("MODEL_DURATION_LIMIT", "error", f"shots[{index}].duration_seconds", "镜头时长超过模型配置上限", shot_id=shot_id, duration=duration, limit=profile["max_duration_seconds"]))
        if profile["supported_fps"] and fps not in profile["supported_fps"]:
            shot_issues.append(make_issue("MODEL_FPS_UNSUPPORTED", "warning", f"shots[{index}].project.fps", "模型配置未声明支持该帧率", shot_id=shot_id, fps=fps, supported=profile["supported_fps"]))
        transition = shot.get("transition", {})
        if transition.get("entry_frame") and not profile["supports_first_frame"]:
            shot_issues.append(make_issue("FIRST_FRAME_UNSUPPORTED", "warning", f"shots[{index}].transition.entry_frame", "模型配置不支持首帧约束", shot_id=shot_id))
        if transition.get("exit_frame") and not profile["supports_last_frame"]:
            shot_issues.append(make_issue("LAST_FRAME_UNSUPPORTED", "warning", f"shots[{index}].transition.exit_frame", "模型配置不支持尾帧约束", shot_id=shot_id))
        if shot.get("negative_prompt") and not profile["supports_negative_prompt"]:
            shot_issues.append(make_issue("NEGATIVE_PROMPT_UNSUPPORTED", "info", f"shots[{index}].negative_prompt", "模型配置不使用负向提示词", shot_id=shot_id))
        relevant_refs = [item for item in approved_refs if not item.get("shot_id") or item.get("shot_id") == shot_id]
        if len(relevant_refs) > profile["max_reference_images"]:
            shot_issues.append(make_issue("REFERENCE_LIMIT", "warning", f"shots[{index}].references", "已批准参考帧超过模型配置上限", shot_id=shot_id, available=len(relevant_refs), limit=profile["max_reference_images"]))
        if not profile["supports_seed"]:
            shot_issues.append(make_issue("MODEL_SEED_NONDETERMINISTIC", "info", f"shots[{index}].seed", "模型配置不保证固定种子可复现", shot_id=shot_id))
        issues.extend(shot_issues)
        shots.append({"shot_id": shot_id, "compatible": not any(item["severity"] == "error" for item in shot_issues), "issues": shot_issues})
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "model_compatibility_report",
        "profile_id": profile["profile_id"],
        "sequence_id": obj.get("sequence_id"),
        "compatible": not any(item["severity"] == "error" for item in issues),
        "shots": shots,
        "issues": issues,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def compile_model_prompt(
    manifest: dict[str, Any] | str,
    model_profile: dict[str, Any] | str,
    extra_fields: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Compile prompts through a declarative template; no code execution is allowed."""
    shot = validate_object(manifest, "shot_manifest")
    profile = validate_model_profile(model_profile)
    extras = _mapping(extra_fields, "extra_fields") if extra_fields else {}
    state = shot.get("continuity_state", {})
    transition = shot.get("transition", {})
    fields = {
        "positive_prompt": shot.get("positive_prompt", ""),
        "negative_prompt": shot.get("negative_prompt", ""),
        "shot_id": shot.get("shot", {}).get("shot_id", ""),
        "action": shot.get("shot", {}).get("action", ""),
        "emotion": state.get("emotion", ""),
        "wardrobe": state.get("wardrobe", ""),
        "props": state.get("props", ""),
        "position": state.get("position", ""),
        "entry_frame": transition.get("entry_frame", ""),
        "exit_frame": transition.get("exit_frame", ""),
        "seed": shot.get("seed", 0),
        **{str(key): str(value) for key, value in extras.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key))},
    }

    def render(template: str) -> str:
        placeholders = re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template)
        unknown = sorted(set(placeholders) - set(fields))
        if unknown:
            raise ContinuityValidationError(f"提示词模板包含未知字段：{unknown}")
        return template.format_map(fields).strip()

    positive = render(profile["prompt_template"])
    negative = render(profile["negative_template"]) if profile["supports_negative_prompt"] else ""
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "compiled_model_prompt",
        "profile_id": profile["profile_id"],
        "shot_id": fields["shot_id"],
        "positive_prompt": positive,
        "negative_prompt": negative,
        "seed": fields["seed"] if profile["supports_seed"] else None,
        "source_manifest_fingerprint": shot.get("fingerprint") or manifest_fingerprint(shot),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def select_reference_frames(
    registry: dict[str, Any] | str,
    manifest: dict[str, Any] | str,
    model_profile: dict[str, Any] | str,
    preferred_roles: Iterable[str] = ("identity", "face", "wardrobe", "first_frame", "last_frame"),
) -> dict[str, Any]:
    registry_obj = _mapping(registry, "reference_registry")
    if registry_obj.get("type") != "reference_registry":
        raise ContinuityValidationError("registry 必须是 reference_registry")
    shot = validate_object(manifest, "shot_manifest")
    profile = validate_model_profile(model_profile)
    if registry_obj.get("project_id") != shot.get("project", {}).get("project_id"):
        raise ContinuityValidationError("reference_registry 与镜头不属于同一项目")
    roles = [str(item).strip().lower() for item in preferred_roles if str(item).strip().lower() in REFERENCE_ROLES]
    role_rank = {role: index for index, role in enumerate(roles)}
    shot_id = shot.get("shot", {}).get("shot_id")
    character_id = shot.get("character", {}).get("character_id")
    scene_id = shot.get("scene", {}).get("scene_id")
    candidates: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    for item in registry_obj.get("frames", []):
        if item.get("status") != "approved":
            continue
        role = item.get("role")
        reason = None
        if role in {"identity", "face", "wardrobe", "pose", "prop"} and item.get("character_id") not in {None, character_id}:
            reason = "character_mismatch"
        elif role in {"environment", "location"} and item.get("scene_id") not in {None, scene_id}:
            reason = "scene_mismatch"
        elif item.get("shot_id") not in {None, shot_id}:
            reason = "shot_mismatch"
        elif role == "last_frame" and not profile["supports_last_frame"]:
            reason = "last_frame_unsupported"
        elif role == "first_frame" and not profile["supports_first_frame"]:
            reason = "first_frame_unsupported"
        elif role in {"identity", "face", "wardrobe"} and not profile["supports_identity_reference"]:
            reason = "identity_reference_unsupported"
        if reason:
            ignored.append({"frame_id": item.get("frame_id"), "reason": reason})
            continue
        score = float(item.get("weight", 1.0)) * 100
        if item.get("shot_id") == shot_id:
            score += 80
        if item.get("character_id") == character_id:
            score += 40
        if item.get("scene_id") == scene_id:
            score += 30
        score += max(0, 20 - role_rank.get(role, len(role_rank) + 1) * 3)
        selected = deepcopy(item)
        selected["selection_score"] = round(score, 3)
        candidates.append(selected)
    candidates.sort(key=lambda item: (-item["selection_score"], item.get("frame_id", "")))
    limit = profile["max_reference_images"]
    selected = candidates[:limit]
    for item in candidates[limit:]:
        ignored.append({"frame_id": item.get("frame_id"), "reason": "model_reference_limit"})
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "reference_selection",
        "profile_id": profile["profile_id"],
        "shot_id": shot_id,
        "selected": selected,
        "ignored": ignored,
        "selected_count": len(selected),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def estimate_generation_cost(
    sequence: dict[str, Any] | str,
    model_profile: dict[str, Any] | str,
    take_count: int = 1,
    resolution: str = "default",
) -> dict[str, Any]:
    obj = validate_object(sequence, "sequence_manifest")
    profile = validate_model_profile(model_profile)
    count = max(1, min(int(take_count), 16))
    resolution_key = str(resolution).strip().lower() or "default"
    multiplier = float(profile.get("resolution_multipliers", {}).get(resolution_key, 1.0))
    if multiplier < 0:
        raise ContinuityValidationError("分辨率成本倍率不能为负数")
    rows: list[dict[str, Any]] = []
    total = 0.0
    for shot in obj.get("shots", []):
        duration = max(0.0, float(shot.get("shot", {}).get("duration_seconds", 0.0)))
        per_take = (profile["base_cost_per_task"] + duration * profile["cost_per_second"]) * multiplier
        cost = per_take * count
        total += cost
        rows.append({
            "shot_id": shot.get("shot", {}).get("shot_id"),
            "duration_seconds": duration,
            "take_count": count,
            "estimated_cost": round(cost, 6),
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "generation_cost_estimate",
        "profile_id": profile["profile_id"],
        "sequence_id": obj.get("sequence_id"),
        "currency": str(profile.get("extra", {}).get("currency", "unit")),
        "resolution": resolution_key,
        "resolution_multiplier": multiplier,
        "take_count": count,
        "shots": rows,
        "estimated_total": round(total, 6),
        "is_zero_cost_profile": total == 0.0,
        "disclaimer": "估算只使用本地模型配置，不代表平台实际账单。",
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def compile_execution_plan(
    sequence: dict[str, Any] | str,
    model_profile: dict[str, Any] | str,
    reference_registry: dict[str, Any] | str | None = None,
    provider: str = "generic",
    max_parallel: int = 2,
    take_count: int = 1,
    retry_policy: dict[str, Any] | str | None = None,
    extra_dependencies: list[dict[str, Any]] | str | None = None,
) -> dict[str, Any]:
    """Compile all deterministic runtime artifacts without sending any external request."""
    obj = validate_object(sequence, "sequence_manifest")
    profile = validate_model_profile(model_profile)
    compatibility = match_sequence_to_model(obj, profile, reference_registry)
    graph = compile_dependency_graph(obj, extra_dependencies)
    waves = schedule_execution_waves(graph, max_parallel) if graph.get("valid") else None
    queue = compile_task_queue(obj, provider, profile, graph, take_count) if graph.get("valid") else None
    retry = _mapping(retry_policy, "retry_policy") if retry_policy else build_retry_policy()
    if retry.get("type") != "retry_policy":
        raise ContinuityValidationError("retry_policy 类型错误")
    cost = estimate_generation_cost(obj, profile, take_count)
    shots: list[dict[str, Any]] = []
    registry = _mapping(reference_registry, "reference_registry") if reference_registry else None
    for shot in obj.get("shots", []):
        compiled_prompt = compile_model_prompt(shot, profile)
        refs = select_reference_frames(registry, shot, profile) if registry else None
        shots.append({
            "shot_id": shot.get("shot", {}).get("shot_id"),
            "compiled_prompt": compiled_prompt,
            "reference_selection": refs,
        })
    blocking = [item for item in compatibility.get("issues", []) if item.get("severity") == "error"]
    plan = {
        "schema_version": SCHEMA_VERSION,
        "type": "generation_execution_plan",
        "project_id": obj.get("project_id"),
        "sequence_id": obj.get("sequence_id"),
        "profile": profile,
        "provider": provider,
        "compatibility": compatibility,
        "dependency_graph": graph,
        "execution_waves": waves,
        "task_queue": queue,
        "retry_policy": retry,
        "cost_estimate": cost,
        "shots": shots,
        "blocked": bool(blocking) or not graph.get("valid", False),
        "blocking_issues": blocking + graph.get("issues", []),
    }
    plan["fingerprint"] = manifest_fingerprint(plan)
    return plan


def diagnose_execution_plan(plan: dict[str, Any] | str) -> dict[str, Any]:
    obj = _mapping(plan, "execution_plan")
    if obj.get("type") != "generation_execution_plan":
        raise ContinuityValidationError("plan 必须是 generation_execution_plan")
    graph = obj.get("dependency_graph") or {}
    waves = obj.get("execution_waves") or {}
    queue = obj.get("task_queue") or {}
    issues: list[dict[str, Any]] = deepcopy(obj.get("blocking_issues", []))
    nodes = graph.get("nodes", [])
    deps = graph.get("dependencies", {})
    depth: dict[str, int] = {}
    for node in graph.get("topological_order", []):
        depth[node] = 1 + max((depth.get(parent, 0) for parent in deps.get(node, [])), default=0)
    critical_depth = max(depth.values(), default=0)
    wave_rows = waves.get("waves", [])
    max_parallel = max(1, int(waves.get("max_parallel", 1)))
    used_slots = sum(int(row.get("parallel_count", 0)) for row in wave_rows)
    available_slots = max(1, len(wave_rows) * max_parallel)
    utilization = round(used_slots / available_slots, 4)
    if len(nodes) > 2 and utilization < 0.5:
        issues.append(make_issue("LOW_PARALLEL_UTILIZATION", "info", "execution_waves", "依赖链较长，并行槽位利用率较低", utilization=utilization))
    reference_coverage = []
    for item in obj.get("shots", []):
        selection = item.get("reference_selection")
        selected_count = selection.get("selected_count", 0) if selection else 0
        reference_coverage.append({"shot_id": item.get("shot_id"), "selected_count": selected_count})
        if selection is not None and selected_count == 0:
            issues.append(make_issue("NO_APPROVED_REFERENCE", "warning", f"shots.{item.get('shot_id')}.references", "该镜头没有选中已批准参考帧"))
    tasks = queue.get("tasks", [])
    duplicate_payloads: dict[str, list[str]] = {}
    for task in tasks:
        key = _sha({"payload": task.get("payload"), "seed": task.get("seed")})
        duplicate_payloads.setdefault(key, []).append(task.get("task_id"))
    duplicates = [ids for ids in duplicate_payloads.values() if len(ids) > 1]
    if duplicates:
        issues.append(make_issue("DUPLICATE_TASK_PAYLOAD", "warning", "task_queue.tasks", "多个任务拥有完全相同的载荷与种子", groups=duplicates))
    error_count = sum(1 for item in issues if item.get("severity") == "error")
    warning_count = sum(1 for item in issues if item.get("severity") == "warning")
    score = max(0, 100 - error_count * 30 - warning_count * 8)
    report = {
        "schema_version": SCHEMA_VERSION,
        "type": "execution_diagnostic_report",
        "plan_fingerprint": obj.get("fingerprint"),
        "ready": not obj.get("blocked") and error_count == 0,
        "score": score,
        "metrics": {
            "shot_count": len(nodes),
            "task_count": queue.get("task_count", 0),
            "wave_count": waves.get("wave_count", 0),
            "critical_path_depth": critical_depth,
            "parallel_utilization": utilization,
            "estimated_cost": obj.get("cost_estimate", {}).get("estimated_total", 0.0),
            "reference_coverage": reference_coverage,
        },
        "issues": issues,
    }
    report["fingerprint"] = manifest_fingerprint(report)
    return report
