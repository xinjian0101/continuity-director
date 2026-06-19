from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from continuity_core import ContinuityValidationError, PACKAGE_VERSION, SCHEMA_VERSION, manifest_fingerprint, slugify

COLLABORATION_ROLES = {"owner", "director", "editor", "reviewer", "operator", "viewer"}
ROLE_PERMISSIONS = {
    "owner": {"read", "edit", "lock", "review", "approve", "operate", "admin"},
    "director": {"read", "edit", "lock", "review", "approve", "operate"},
    "editor": {"read", "edit", "lock"},
    "reviewer": {"read", "review", "approve"},
    "operator": {"read", "operate"},
    "viewer": {"read"},
}
APPROVAL_STATES = {"draft", "in_review", "changes_requested", "approved", "rejected", "superseded"}
WORKER_STATES = {"online", "busy", "draining", "offline", "stale"}


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


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _sha(value: Any, length: int = 64) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _now_ms(value: int | None = None) -> int:
    return int(time.time() * 1000) if value is None else int(value)


def _member_id(value: Any) -> str:
    return slugify(_clean(value), "member")


def _ensure_member(manifest: dict[str, Any], member_id: str) -> dict[str, Any]:
    for member in manifest.get("members", []):
        if member.get("member_id") == member_id:
            return member
    raise ContinuityValidationError(f"协作成员不存在：{member_id}")


def _require_permission(manifest: dict[str, Any], member_id: str, permission: str) -> dict[str, Any]:
    member = _ensure_member(manifest, member_id)
    permissions = set(member.get("permissions", []))
    if permission not in permissions:
        raise ContinuityValidationError(f"成员 {member_id} 缺少权限：{permission}")
    return member


def create_collaboration_manifest(
    project_id: str,
    members: list[dict[str, Any]] | str,
    created_by: str,
    policy: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Create a deterministic project collaboration manifest with explicit RBAC."""
    pid = slugify(project_id, "project")
    rows = _list(members, "members")
    if not rows:
        raise ContinuityValidationError("members 至少需要一个成员")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    owner_count = 0
    for raw in rows:
        if not isinstance(raw, dict):
            raise ContinuityValidationError("members 中每项必须是对象")
        member_id = _member_id(raw.get("member_id") or raw.get("id") or raw.get("name"))
        if member_id in seen:
            raise ContinuityValidationError(f"成员 ID 重复：{member_id}")
        seen.add(member_id)
        role = _clean(raw.get("role") or "viewer").lower()
        if role not in COLLABORATION_ROLES:
            raise ContinuityValidationError(f"不支持的协作角色：{role}")
        if role == "owner":
            owner_count += 1
        extra_permissions = {_clean(item).lower() for item in raw.get("extra_permissions", []) if _clean(item)}
        denied_permissions = {_clean(item).lower() for item in raw.get("denied_permissions", []) if _clean(item)}
        permissions = sorted((ROLE_PERMISSIONS[role] | extra_permissions) - denied_permissions)
        normalized.append({
            "member_id": member_id,
            "display_name": _clean(raw.get("display_name") or raw.get("name") or member_id),
            "role": role,
            "permissions": permissions,
            "active": bool(raw.get("active", True)),
            "metadata": deepcopy(raw.get("metadata", {})) if isinstance(raw.get("metadata", {}), dict) else {},
        })
    if owner_count != 1:
        raise ContinuityValidationError("协作项目必须且只能有一个 owner")
    creator = _member_id(created_by)
    creator_row = next((item for item in normalized if item["member_id"] == creator), None)
    if not creator_row:
        raise ContinuityValidationError("created_by 必须属于 members")
    if creator_row["role"] != "owner":
        raise ContinuityValidationError("created_by 必须是 owner")
    policy_data = _mapping(policy or {}, "policy")
    stamp = _now_ms(now_ms)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "collaboration_manifest",
        "project_id": pid,
        "created_by": creator,
        "created_at_ms": stamp,
        "updated_at_ms": stamp,
        "members": normalized,
        "member_count": len(normalized),
        "policy": {
            "require_review_before_approval": bool(policy_data.get("require_review_before_approval", True)),
            "minimum_approvals": max(1, int(policy_data.get("minimum_approvals", 1))),
            "lock_ttl_seconds": max(30, min(86400, int(policy_data.get("lock_ttl_seconds", 900)))),
            "allow_self_approval": bool(policy_data.get("allow_self_approval", False)),
        },
        "package_version": PACKAGE_VERSION,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def acquire_edit_lock(
    collaboration: dict[str, Any] | str,
    lock_state: dict[str, Any] | str | None,
    member_id: str,
    resource_type: str,
    resource_id: str,
    ttl_seconds: int | None = None,
    expected_revision: int | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Acquire or renew a lease-based edit lock with optimistic revision checking."""
    manifest = _mapping(collaboration, "collaboration")
    actor = _member_id(member_id)
    _require_permission(manifest, actor, "lock")
    state = _mapping(lock_state or {"type": "edit_lock_state", "revision": 0, "locks": []}, "lock_state")
    if state.get("type") != "edit_lock_state":
        raise ContinuityValidationError("lock_state 类型错误")
    revision = int(state.get("revision", 0))
    if expected_revision is not None and revision != int(expected_revision):
        raise ContinuityValidationError(f"锁状态修订冲突：expected={expected_revision}, actual={revision}")
    stamp = _now_ms(now_ms)
    ttl = int(ttl_seconds or manifest.get("policy", {}).get("lock_ttl_seconds", 900))
    ttl = max(30, min(86400, ttl))
    key = f"{slugify(resource_type, 'resource')}:{slugify(resource_id, 'item')}"
    active: list[dict[str, Any]] = []
    existing: dict[str, Any] | None = None
    for raw in state.get("locks", []):
        if not isinstance(raw, dict):
            continue
        if int(raw.get("expires_at_ms", 0)) <= stamp:
            continue
        if raw.get("lock_key") == key:
            existing = raw
        else:
            active.append(deepcopy(raw))
    if existing and existing.get("holder_id") != actor:
        raise ContinuityValidationError(f"资源已被 {existing.get('holder_id')} 锁定")
    lock = {
        "lock_key": key,
        "resource_type": slugify(resource_type, "resource"),
        "resource_id": slugify(resource_id, "item"),
        "holder_id": actor,
        "acquired_at_ms": int(existing.get("acquired_at_ms", stamp)) if existing else stamp,
        "renewed_at_ms": stamp,
        "expires_at_ms": stamp + ttl * 1000,
        "lease_token": _sha([manifest.get("project_id"), key, actor, stamp], 32),
    }
    active.append(lock)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "edit_lock_state",
        "project_id": manifest.get("project_id"),
        "revision": revision + 1,
        "updated_at_ms": stamp,
        "locks": sorted(active, key=lambda item: item["lock_key"]),
        "active_lock_count": len(active),
        "last_acquired": lock,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def release_edit_lock(
    collaboration: dict[str, Any] | str,
    lock_state: dict[str, Any] | str,
    member_id: str,
    resource_type: str,
    resource_id: str,
    lease_token: str = "",
    force: bool = False,
    now_ms: int | None = None,
) -> dict[str, Any]:
    manifest = _mapping(collaboration, "collaboration")
    state = _mapping(lock_state, "lock_state")
    actor = _member_id(member_id)
    member = _ensure_member(manifest, actor)
    key = f"{slugify(resource_type, 'resource')}:{slugify(resource_id, 'item')}"
    removed = None
    retained: list[dict[str, Any]] = []
    stamp = _now_ms(now_ms)
    for raw in state.get("locks", []):
        if not isinstance(raw, dict):
            continue
        if raw.get("lock_key") != key:
            if int(raw.get("expires_at_ms", 0)) > stamp:
                retained.append(deepcopy(raw))
            continue
        if raw.get("holder_id") != actor:
            if not force or "admin" not in member.get("permissions", []):
                raise ContinuityValidationError("只能释放自己的锁；管理员可使用 force")
        if lease_token and raw.get("lease_token") != lease_token:
            raise ContinuityValidationError("lease_token 不匹配")
        removed = deepcopy(raw)
    if removed is None:
        raise ContinuityValidationError(f"未找到活动锁：{key}")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "edit_lock_state",
        "project_id": manifest.get("project_id"),
        "revision": int(state.get("revision", 0)) + 1,
        "updated_at_ms": stamp,
        "locks": retained,
        "active_lock_count": len(retained),
        "last_released": {**removed, "released_by": actor, "released_at_ms": stamp, "forced": bool(force)},
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def create_approval_record(
    collaboration: dict[str, Any] | str,
    resource_type: str,
    resource_id: str,
    author_id: str,
    content_fingerprint: str,
    title: str = "",
    now_ms: int | None = None,
) -> dict[str, Any]:
    manifest = _mapping(collaboration, "collaboration")
    author = _member_id(author_id)
    _require_permission(manifest, author, "edit")
    stamp = _now_ms(now_ms)
    record = {
        "schema_version": SCHEMA_VERSION,
        "type": "approval_record",
        "approval_id": f"approval-{_sha([manifest.get('project_id'), resource_type, resource_id, content_fingerprint], 16)}",
        "project_id": manifest.get("project_id"),
        "resource_type": slugify(resource_type, "resource"),
        "resource_id": slugify(resource_id, "item"),
        "title": _clean(title),
        "author_id": author,
        "content_fingerprint": _clean(content_fingerprint),
        "state": "draft",
        "revision": 1,
        "reviewers": [],
        "approvals": [],
        "events": [{"event": "created", "actor_id": author, "timestamp_ms": stamp}],
        "created_at_ms": stamp,
        "updated_at_ms": stamp,
    }
    record["fingerprint"] = manifest_fingerprint(record)
    return record


def transition_approval(
    collaboration: dict[str, Any] | str,
    approval_record: dict[str, Any] | str,
    actor_id: str,
    action: str,
    comment: str = "",
    expected_revision: int | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    manifest = _mapping(collaboration, "collaboration")
    record = _mapping(approval_record, "approval_record")
    if record.get("type") != "approval_record":
        raise ContinuityValidationError("approval_record 类型错误")
    actor = _member_id(actor_id)
    member = _ensure_member(manifest, actor)
    revision = int(record.get("revision", 0))
    if expected_revision is not None and revision != int(expected_revision):
        raise ContinuityValidationError("审批记录修订冲突")
    state = _clean(record.get("state")).lower()
    command = _clean(action).lower()
    transitions = {
        ("draft", "submit"): "in_review",
        ("changes_requested", "resubmit"): "in_review",
        ("in_review", "request_changes"): "changes_requested",
        ("in_review", "reject"): "rejected",
        ("in_review", "approve"): "approved",
        ("approved", "supersede"): "superseded",
        ("rejected", "revise"): "draft",
    }
    target = transitions.get((state, command))
    if not target:
        raise ContinuityValidationError(f"不允许的审批转换：{state} -> {command}")
    permission = "edit" if command in {"submit", "resubmit", "revise"} else "approve"
    if permission not in member.get("permissions", []):
        raise ContinuityValidationError(f"成员缺少审批动作权限：{permission}")
    if command in {"submit", "resubmit", "revise", "supersede"} and actor != record.get("author_id") and "admin" not in member.get("permissions", []):
        raise ContinuityValidationError("该动作只能由作者或管理员执行")
    if command == "approve":
        if actor == record.get("author_id") and not manifest.get("policy", {}).get("allow_self_approval", False):
            raise ContinuityValidationError("项目策略禁止作者自审")
        approvals = list(record.get("approvals", []))
        if actor not in approvals:
            approvals.append(actor)
        record["approvals"] = approvals
        required = int(manifest.get("policy", {}).get("minimum_approvals", 1))
        if len(approvals) < required:
            target = "in_review"
    if command == "request_changes" and not _clean(comment):
        raise ContinuityValidationError("request_changes 必须填写 comment")
    reviewers = list(record.get("reviewers", []))
    if command in {"approve", "request_changes", "reject"} and actor not in reviewers:
        reviewers.append(actor)
    record["reviewers"] = reviewers
    stamp = _now_ms(now_ms)
    record["state"] = target
    record["revision"] = revision + 1
    record["updated_at_ms"] = stamp
    record.setdefault("events", []).append({
        "event": command,
        "from_state": state,
        "to_state": target,
        "actor_id": actor,
        "comment": _clean(comment),
        "timestamp_ms": stamp,
    })
    record["fingerprint"] = manifest_fingerprint(record)
    return record


def create_change_request(
    collaboration: dict[str, Any] | str,
    requester_id: str,
    target_resource: dict[str, Any] | str,
    proposed_patch: dict[str, Any] | str,
    summary: str,
    reviewers: list[str] | str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    manifest = _mapping(collaboration, "collaboration")
    requester = _member_id(requester_id)
    _require_permission(manifest, requester, "edit")
    target = _mapping(target_resource, "target_resource")
    patch = _mapping(proposed_patch, "proposed_patch")
    reviewer_ids = [_member_id(item) for item in _list(reviewers or [], "reviewers")]
    for reviewer in reviewer_ids:
        _require_permission(manifest, reviewer, "review")
    stamp = _now_ms(now_ms)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "change_request",
        "request_id": f"cr-{_sha([manifest.get('project_id'), requester, target, patch, stamp], 16)}",
        "project_id": manifest.get("project_id"),
        "requester_id": requester,
        "summary": _clean(summary),
        "status": "open",
        "base_fingerprint": manifest_fingerprint(target),
        "target_resource": target,
        "proposed_patch": patch,
        "reviewers": sorted(set(reviewer_ids)),
        "reviews": [],
        "created_at_ms": stamp,
        "updated_at_ms": stamp,
        "revision": 1,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def review_change_request(
    collaboration: dict[str, Any] | str,
    change_request: dict[str, Any] | str,
    reviewer_id: str,
    decision: str,
    comment: str = "",
    expected_revision: int | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    manifest = _mapping(collaboration, "collaboration")
    request = _mapping(change_request, "change_request")
    reviewer = _member_id(reviewer_id)
    _require_permission(manifest, reviewer, "review")
    if request.get("status") not in {"open", "changes_requested"}:
        raise ContinuityValidationError("当前变更请求不可评审")
    revision = int(request.get("revision", 0))
    if expected_revision is not None and revision != int(expected_revision):
        raise ContinuityValidationError("变更请求修订冲突")
    verdict = _clean(decision).lower()
    if verdict not in {"approve", "request_changes", "reject"}:
        raise ContinuityValidationError("decision 必须是 approve/request_changes/reject")
    if verdict != "approve" and not _clean(comment):
        raise ContinuityValidationError("非批准决定必须填写 comment")
    reviews = [item for item in request.get("reviews", []) if item.get("reviewer_id") != reviewer]
    stamp = _now_ms(now_ms)
    reviews.append({"reviewer_id": reviewer, "decision": verdict, "comment": _clean(comment), "timestamp_ms": stamp})
    request["reviews"] = sorted(reviews, key=lambda item: item["reviewer_id"])
    decisions = {item["decision"] for item in reviews}
    if "reject" in decisions:
        status = "rejected"
    elif "request_changes" in decisions:
        status = "changes_requested"
    else:
        required = int(manifest.get("policy", {}).get("minimum_approvals", 1))
        approvals = sum(1 for item in reviews if item["decision"] == "approve")
        status = "approved" if approvals >= required else "open"
    request["status"] = status
    request["updated_at_ms"] = stamp
    request["revision"] = revision + 1
    request["fingerprint"] = manifest_fingerprint(request)
    return request


def append_audit_event(
    audit_log: dict[str, Any] | str | None,
    project_id: str,
    actor_id: str,
    event_type: str,
    payload: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Append an event to a tamper-evident SHA-256 hash chain."""
    log = _mapping(audit_log or {"type": "collaboration_audit_log", "events": []}, "audit_log")
    if log.get("type") != "collaboration_audit_log":
        raise ContinuityValidationError("audit_log 类型错误")
    events = deepcopy(log.get("events", []))
    if not isinstance(events, list):
        raise ContinuityValidationError("audit_log.events 必须是数组")
    sequence = len(events) + 1
    previous_hash = events[-1].get("event_hash", "0" * 64) if events else "0" * 64
    stamp = _now_ms(now_ms)
    event = {
        "sequence": sequence,
        "timestamp_ms": stamp,
        "project_id": slugify(project_id, "project"),
        "actor_id": _member_id(actor_id),
        "event_type": slugify(event_type, "event"),
        "payload": _mapping(payload or {}, "payload"),
        "previous_hash": previous_hash,
    }
    event["event_hash"] = _sha(event)
    events.append(event)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "collaboration_audit_log",
        "project_id": event["project_id"],
        "events": events,
        "event_count": len(events),
        "head_hash": event["event_hash"],
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def verify_audit_log(audit_log: dict[str, Any] | str) -> dict[str, Any]:
    log = _mapping(audit_log, "audit_log")
    issues: list[dict[str, Any]] = []
    previous_hash = "0" * 64
    for index, raw in enumerate(log.get("events", []), start=1):
        if not isinstance(raw, dict):
            issues.append({"sequence": index, "code": "invalid_event", "message": "审计事件必须是对象"})
            continue
        event = deepcopy(raw)
        event_hash = event.pop("event_hash", "")
        if int(event.get("sequence", 0)) != index:
            issues.append({"sequence": index, "code": "sequence_mismatch", "message": "审计序号不连续"})
        if event.get("previous_hash") != previous_hash:
            issues.append({"sequence": index, "code": "previous_hash_mismatch", "message": "前序哈希不匹配"})
        expected = _sha(event)
        if event_hash != expected:
            issues.append({"sequence": index, "code": "event_hash_mismatch", "message": "事件内容已被修改"})
        previous_hash = event_hash
    if log.get("events") and log.get("head_hash") != previous_hash:
        issues.append({"sequence": len(log.get("events", [])), "code": "head_hash_mismatch", "message": "审计链头哈希错误"})
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "audit_verification",
        "valid": not issues,
        "event_count": len(log.get("events", [])),
        "issue_count": len(issues),
        "issues": issues,
        "head_hash": previous_hash,
    }


_MISSING = object()


def _path_join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _three_way_node(base: Any, ours: Any, theirs: Any, path: str, conflicts: list[dict[str, Any]], strategy: str) -> Any:
    if ours == theirs:
        return deepcopy(ours)
    if ours == base:
        return deepcopy(theirs)
    if theirs == base:
        return deepcopy(ours)
    if all(isinstance(value, dict) for value in (base, ours, theirs)):
        merged: dict[str, Any] = {}
        keys = sorted(set(base) | set(ours) | set(theirs))
        for key in keys:
            b = base.get(key, _MISSING)
            o = ours.get(key, _MISSING)
            t = theirs.get(key, _MISSING)
            child_path = _path_join(path, str(key))
            if o is _MISSING and t is _MISSING:
                continue
            if b is _MISSING:
                if o is _MISSING:
                    merged[key] = deepcopy(t)
                elif t is _MISSING or o == t:
                    merged[key] = deepcopy(o)
                else:
                    conflicts.append({"path": child_path, "base": None, "ours": deepcopy(o), "theirs": deepcopy(t), "kind": "both_added"})
                    merged[key] = deepcopy(o if strategy != "theirs" else t)
                continue
            if o is _MISSING:
                if t == b:
                    continue
                conflicts.append({"path": child_path, "base": deepcopy(b), "ours": None, "theirs": deepcopy(t), "kind": "delete_modify"})
                if strategy == "theirs":
                    merged[key] = deepcopy(t)
                continue
            if t is _MISSING:
                if o == b:
                    continue
                conflicts.append({"path": child_path, "base": deepcopy(b), "ours": deepcopy(o), "theirs": None, "kind": "modify_delete"})
                if strategy != "theirs":
                    merged[key] = deepcopy(o)
                continue
            merged[key] = _three_way_node(b, o, t, child_path, conflicts, strategy)
        return merged
    conflicts.append({"path": path or "$", "base": deepcopy(base), "ours": deepcopy(ours), "theirs": deepcopy(theirs), "kind": "both_modified"})
    return deepcopy(theirs if strategy == "theirs" else ours)


def three_way_merge(
    base: dict[str, Any] | str,
    ours: dict[str, Any] | str,
    theirs: dict[str, Any] | str,
    conflict_strategy: str = "manual",
) -> dict[str, Any]:
    """Merge concurrent JSON edits. Lists are treated atomically to avoid unsafe index merging."""
    base_obj = _mapping(base, "base")
    ours_obj = _mapping(ours, "ours")
    theirs_obj = _mapping(theirs, "theirs")
    strategy = _clean(conflict_strategy).lower()
    if strategy not in {"manual", "ours", "theirs"}:
        raise ContinuityValidationError("conflict_strategy 必须是 manual/ours/theirs")
    conflicts: list[dict[str, Any]] = []
    merged = _three_way_node(base_obj, ours_obj, theirs_obj, "", conflicts, strategy)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "three_way_merge",
        "strategy": strategy,
        "base_fingerprint": manifest_fingerprint(base_obj),
        "ours_fingerprint": manifest_fingerprint(ours_obj),
        "theirs_fingerprint": manifest_fingerprint(theirs_obj),
        "merged": merged,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "clean": not conflicts,
        "requires_manual_resolution": bool(conflicts and strategy == "manual"),
    }
    result["merged_fingerprint"] = manifest_fingerprint(merged)
    return result


def register_worker(
    worker_registry: dict[str, Any] | str | None,
    worker_id: str,
    capabilities: dict[str, Any] | str,
    labels: dict[str, Any] | str | None = None,
    capacity: int = 1,
    now_ms: int | None = None,
) -> dict[str, Any]:
    registry = _mapping(worker_registry or {"type": "worker_registry", "revision": 0, "workers": []}, "worker_registry")
    if registry.get("type") != "worker_registry":
        raise ContinuityValidationError("worker_registry 类型错误")
    wid = slugify(worker_id, "worker")
    capability_data = _mapping(capabilities, "capabilities")
    label_data = _mapping(labels or {}, "labels")
    stamp = _now_ms(now_ms)
    workers = [deepcopy(item) for item in registry.get("workers", []) if isinstance(item, dict) and item.get("worker_id") != wid]
    worker = {
        "worker_id": wid,
        "state": "online",
        "capabilities": capability_data,
        "labels": label_data,
        "capacity": max(1, min(128, int(capacity))),
        "active_tasks": 0,
        "registered_at_ms": stamp,
        "last_heartbeat_ms": stamp,
        "generation": 1,
    }
    previous = next((item for item in registry.get("workers", []) if isinstance(item, dict) and item.get("worker_id") == wid), None)
    if previous:
        worker["registered_at_ms"] = int(previous.get("registered_at_ms", stamp))
        worker["generation"] = int(previous.get("generation", 0)) + 1
        worker["active_tasks"] = min(worker["capacity"], max(0, int(previous.get("active_tasks", 0))))
    worker["worker_fingerprint"] = manifest_fingerprint(worker)
    workers.append(worker)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "worker_registry",
        "revision": int(registry.get("revision", 0)) + 1,
        "updated_at_ms": stamp,
        "workers": sorted(workers, key=lambda item: item["worker_id"]),
        "worker_count": len(workers),
        "last_registered": wid,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def update_worker_heartbeat(
    worker_registry: dict[str, Any] | str,
    worker_id: str,
    state: str = "online",
    active_tasks: int | None = None,
    metrics: dict[str, Any] | str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    registry = _mapping(worker_registry, "worker_registry")
    wid = slugify(worker_id, "worker")
    target_state = _clean(state).lower()
    if target_state not in WORKER_STATES - {"stale"}:
        raise ContinuityValidationError("worker state 必须是 online/busy/draining/offline")
    stamp = _now_ms(now_ms)
    found = False
    workers: list[dict[str, Any]] = []
    for raw in registry.get("workers", []):
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        if item.get("worker_id") == wid:
            found = True
            item["state"] = target_state
            item["last_heartbeat_ms"] = stamp
            if active_tasks is not None:
                item["active_tasks"] = max(0, min(int(item.get("capacity", 1)), int(active_tasks)))
            item["metrics"] = _mapping(metrics or item.get("metrics", {}), "metrics")
            item["worker_fingerprint"] = manifest_fingerprint(item)
        workers.append(item)
    if not found:
        raise ContinuityValidationError(f"worker 不存在：{wid}")
    result = {**registry, "revision": int(registry.get("revision", 0)) + 1, "updated_at_ms": stamp, "workers": workers}
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def detect_stale_workers(worker_registry: dict[str, Any] | str, stale_after_seconds: int = 120, now_ms: int | None = None) -> dict[str, Any]:
    registry = _mapping(worker_registry, "worker_registry")
    stamp = _now_ms(now_ms)
    threshold = max(10, int(stale_after_seconds)) * 1000
    workers: list[dict[str, Any]] = []
    stale_ids: list[str] = []
    for raw in registry.get("workers", []):
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        age = stamp - int(item.get("last_heartbeat_ms", 0))
        item["heartbeat_age_ms"] = max(0, age)
        if item.get("state") not in {"offline", "draining"} and age > threshold:
            item["state"] = "stale"
            stale_ids.append(item.get("worker_id"))
        workers.append(item)
    result = {
        **registry,
        "type": "worker_registry_health",
        "checked_at_ms": stamp,
        "stale_after_seconds": max(10, int(stale_after_seconds)),
        "workers": workers,
        "stale_worker_ids": stale_ids,
        "stale_worker_count": len(stale_ids),
        "healthy": not stale_ids,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def schedule_distributed_tasks(
    generation_queue: dict[str, Any] | str,
    worker_registry: dict[str, Any] | str,
    max_assignments: int = 100,
) -> dict[str, Any]:
    """Assign queued tasks to healthy workers using capabilities, capacity and deterministic ordering."""
    queue = _mapping(generation_queue, "generation_queue")
    registry = _mapping(worker_registry, "worker_registry")
    workers = []
    for raw in registry.get("workers", []):
        if not isinstance(raw, dict) or raw.get("state") not in {"online", "busy"}:
            continue
        capacity = max(0, int(raw.get("capacity", 1)) - int(raw.get("active_tasks", 0)))
        if capacity > 0:
            workers.append({**deepcopy(raw), "available_slots": capacity})
    workers.sort(key=lambda item: (int(item.get("active_tasks", 0)), item.get("worker_id", "")))
    succeeded = {item.get("shot_id") for item in queue.get("tasks", []) if isinstance(item, dict) and item.get("status") == "succeeded"}
    tasks = [deepcopy(item) for item in queue.get("tasks", []) if isinstance(item, dict) and item.get("status") == "queued"]
    tasks.sort(key=lambda item: (-int(item.get("priority", 0)), int(item.get("created_at_ms", 0)), item.get("task_id", "")))
    assignments: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    limit = max(1, min(10000, int(max_assignments)))

    def worker_matches(worker: dict[str, Any], task: dict[str, Any]) -> tuple[bool, list[str]]:
        caps = worker.get("capabilities", {}) if isinstance(worker.get("capabilities", {}), dict) else {}
        requirements = task.get("requirements", {}) if isinstance(task.get("requirements", {}), dict) else {}
        reasons: list[str] = []
        model = _clean(requirements.get("model_profile") or task.get("model_profile"))
        models = set(caps.get("model_profiles", []))
        if model and models and model not in models:
            reasons.append("model_profile")
        transport = _clean(requirements.get("transport"))
        transports = set(caps.get("transports", []))
        if transport and transports and transport not in transports:
            reasons.append("transport")
        min_vram = float(requirements.get("min_vram_gb", 0) or 0)
        if min_vram and float(caps.get("vram_gb", 0) or 0) < min_vram:
            reasons.append("vram")
        required_labels = requirements.get("labels", {}) if isinstance(requirements.get("labels", {}), dict) else {}
        worker_labels = worker.get("labels", {}) if isinstance(worker.get("labels", {}), dict) else {}
        for key, value in required_labels.items():
            if worker_labels.get(key) != value:
                reasons.append(f"label:{key}")
        return not reasons, reasons

    for task in tasks:
        if len(assignments) >= limit:
            break
        dependencies = task.get("requires_shots", task.get("dependencies", []))
        if isinstance(dependencies, list) and any(dep not in succeeded for dep in dependencies):
            blocked.append({"task_id": task.get("task_id"), "reason": "dependencies_not_satisfied"})
            continue
        candidates: list[dict[str, Any]] = []
        mismatches: dict[str, list[str]] = {}
        for worker in workers:
            if int(worker.get("available_slots", 0)) <= 0:
                continue
            matched, reasons = worker_matches(worker, task)
            if matched:
                candidates.append(worker)
            else:
                mismatches[worker.get("worker_id", "unknown")] = reasons
        if not candidates:
            blocked.append({"task_id": task.get("task_id"), "reason": "no_compatible_worker", "mismatches": mismatches})
            continue
        candidates.sort(key=lambda item: (int(item.get("active_tasks", 0)), -int(item.get("available_slots", 0)), item.get("worker_id", "")))
        worker = candidates[0]
        assignment = {
            "assignment_id": f"assign-{_sha([queue.get('queue_id'), task.get('task_id'), worker.get('worker_id')], 16)}",
            "task_id": task.get("task_id"),
            "shot_id": task.get("shot_id"),
            "worker_id": worker.get("worker_id"),
            "task_fingerprint": task.get("task_fingerprint") or manifest_fingerprint(task),
            "worker_fingerprint": worker.get("worker_fingerprint") or manifest_fingerprint(worker),
        }
        assignments.append(assignment)
        worker["available_slots"] = int(worker.get("available_slots", 0)) - 1
        worker["active_tasks"] = int(worker.get("active_tasks", 0)) + 1
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "distributed_schedule",
        "queue_id": queue.get("queue_id"),
        "queue_revision": queue.get("revision"),
        "registry_revision": registry.get("revision"),
        "assignments": assignments,
        "assignment_count": len(assignments),
        "blocked": blocked,
        "blocked_count": len(blocked),
        "unassigned_task_count": max(0, len(tasks) - len(assignments)),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def build_compatibility_matrix(
    environments: list[dict[str, Any]] | str,
    requirements: dict[str, Any] | str,
) -> dict[str, Any]:
    """Evaluate multiple ComfyUI/plugin/model environments against a declarative requirement set."""
    envs = _list(environments, "environments")
    req = _mapping(requirements, "requirements")
    rows: list[dict[str, Any]] = []
    compatible_ids: list[str] = []
    for raw in envs:
        if not isinstance(raw, dict):
            raise ContinuityValidationError("environments 中每项必须是对象")
        env_id = slugify(raw.get("environment_id") or raw.get("name"), "environment")
        issues: list[dict[str, Any]] = []
        python_version = _clean(raw.get("python_version"))
        min_python = _clean(req.get("min_python"))
        if min_python and python_version and tuple(map(int, python_version.split(".")[:2])) < tuple(map(int, min_python.split(".")[:2])):
            issues.append({"code": "python_too_old", "required": min_python, "actual": python_version})
        comfy_version = _clean(raw.get("comfyui_version"))
        required_comfy = _clean(req.get("comfyui_version"))
        if required_comfy and comfy_version != required_comfy:
            issues.append({"code": "comfyui_version_mismatch", "required": required_comfy, "actual": comfy_version})
        plugins = raw.get("plugins", {}) if isinstance(raw.get("plugins", {}), dict) else {}
        for name, version in (req.get("plugins", {}) if isinstance(req.get("plugins", {}), dict) else {}).items():
            actual = plugins.get(name)
            if actual is None:
                issues.append({"code": "missing_plugin", "plugin": name, "required": version})
            elif str(actual) != str(version):
                issues.append({"code": "plugin_version_mismatch", "plugin": name, "required": version, "actual": actual})
        models = set(raw.get("models", []))
        for model in req.get("models", []) if isinstance(req.get("models", []), list) else []:
            if model not in models:
                issues.append({"code": "missing_model", "model": model})
        ffmpeg_required = bool(req.get("ffmpeg_required", False))
        if ffmpeg_required and not bool(raw.get("ffmpeg_available", False)):
            issues.append({"code": "ffmpeg_missing"})
        min_vram = float(req.get("min_vram_gb", 0) or 0)
        if min_vram and float(raw.get("vram_gb", 0) or 0) < min_vram:
            issues.append({"code": "insufficient_vram", "required": min_vram, "actual": raw.get("vram_gb", 0)})
        compatible = not issues
        if compatible:
            compatible_ids.append(env_id)
        rows.append({
            "environment_id": env_id,
            "compatible": compatible,
            "issue_count": len(issues),
            "issues": issues,
            "environment_fingerprint": manifest_fingerprint(raw),
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "compatibility_matrix",
        "requirements": req,
        "environments": rows,
        "environment_count": len(rows),
        "compatible_environment_ids": compatible_ids,
        "compatible_count": len(compatible_ids),
        "all_compatible": len(compatible_ids) == len(rows),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def create_environment_lockfile(environment: dict[str, Any] | str, project_id: str, generated_by: str = "") -> dict[str, Any]:
    env = _mapping(environment, "environment")
    normalized = {
        "python_version": _clean(env.get("python_version")),
        "comfyui_version": _clean(env.get("comfyui_version")),
        "continuity_director_version": PACKAGE_VERSION,
        "plugins": dict(sorted((env.get("plugins", {}) if isinstance(env.get("plugins", {}), dict) else {}).items())),
        "models": sorted(set(env.get("models", []))) if isinstance(env.get("models", []), list) else [],
        "ffmpeg_version": _clean(env.get("ffmpeg_version")),
        "cuda_version": _clean(env.get("cuda_version")),
        "gpu": _clean(env.get("gpu")),
        "vram_gb": float(env.get("vram_gb", 0) or 0),
        "platform": _clean(env.get("platform")),
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "environment_lockfile",
        "project_id": slugify(project_id, "project"),
        "generated_by": _member_id(generated_by) if generated_by else None,
        "environment": normalized,
    }
    result["environment_fingerprint"] = manifest_fingerprint(normalized)
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def import_bulk_records(
    payload: str,
    input_format: str = "jsonl",
    required_fields: list[str] | str | None = None,
    id_field: str = "shot_id",
    max_records: int = 10000,
) -> dict[str, Any]:
    """Import CSV or JSONL safely with row-level diagnostics and duplicate-ID detection."""
    fmt = _clean(input_format).lower()
    if fmt not in {"jsonl", "csv"}:
        raise ContinuityValidationError("input_format 必须是 jsonl/csv")
    required = [_clean(item) for item in _list(required_fields or [], "required_fields") if _clean(item)]
    limit = max(1, min(100000, int(max_records)))
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    text = str(payload or "")
    if fmt == "jsonl":
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            if len(records) >= limit:
                errors.append({"row": line_number, "code": "record_limit", "message": f"超过最大记录数 {limit}"})
                break
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"row": line_number, "code": "invalid_json", "message": str(exc)})
                continue
            if not isinstance(item, dict):
                errors.append({"row": line_number, "code": "not_object", "message": "每行必须是 JSON 对象"})
                continue
            records.append(item)
    else:
        try:
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                raise ContinuityValidationError("CSV 缺少表头")
            for row_number, row in enumerate(reader, start=2):
                if len(records) >= limit:
                    errors.append({"row": row_number, "code": "record_limit", "message": f"超过最大记录数 {limit}"})
                    break
                records.append({str(key): value for key, value in row.items() if key is not None})
        except csv.Error as exc:
            raise ContinuityValidationError(f"CSV 解析失败：{exc}") from exc
    valid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(records, start=1):
        missing = [field for field in required if item.get(field) in (None, "")]
        if missing:
            errors.append({"row": index, "code": "missing_required", "fields": missing})
            continue
        record_id = _clean(item.get(id_field))
        if record_id:
            if record_id in seen_ids:
                errors.append({"row": index, "code": "duplicate_id", "field": id_field, "value": record_id})
                continue
            seen_ids.add(record_id)
        normalized = deepcopy(item)
        normalized["_import_index"] = index
        normalized["_record_fingerprint"] = manifest_fingerprint(item)
        valid.append(normalized)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "bulk_import_result",
        "input_format": fmt,
        "records": valid,
        "valid_count": len(valid),
        "error_count": len(errors),
        "errors": errors,
        "total_parsed": len(records),
        "complete": not errors,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def validate_template_manifest(template_manifest: dict[str, Any] | str) -> dict[str, Any]:
    """Validate a portable template-market manifest without executing template content."""
    manifest = _mapping(template_manifest, "template_manifest")
    issues: list[dict[str, Any]] = []
    template_id = slugify(manifest.get("template_id") or manifest.get("name"), "template")
    version = _clean(manifest.get("version"))
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        issues.append({"code": "invalid_semver", "field": "version"})
    license_id = _clean(manifest.get("license"))
    if not license_id:
        issues.append({"code": "missing_license", "field": "license"})
    entrypoint = _clean(manifest.get("entrypoint"))
    if not entrypoint or Path(entrypoint).is_absolute() or ".." in Path(entrypoint).parts:
        issues.append({"code": "unsafe_entrypoint", "field": "entrypoint"})
    files = manifest.get("files", [])
    if not isinstance(files, list) or not files:
        issues.append({"code": "missing_files", "field": "files"})
        files = []
    normalized_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(files):
        if not isinstance(raw, dict):
            issues.append({"code": "invalid_file", "index": index})
            continue
        path = _clean(raw.get("path"))
        digest = _clean(raw.get("sha256")).lower()
        if not path or Path(path).is_absolute() or ".." in Path(path).parts:
            issues.append({"code": "unsafe_file_path", "index": index, "path": path})
            continue
        if path in seen_paths:
            issues.append({"code": "duplicate_file_path", "path": path})
            continue
        seen_paths.add(path)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            issues.append({"code": "invalid_sha256", "path": path})
        normalized_files.append({"path": path, "sha256": digest, "size_bytes": max(0, int(raw.get("size_bytes", 0) or 0))})
    minimum_version = _clean((manifest.get("compatibility") or {}).get("continuity_director_min")) if isinstance(manifest.get("compatibility"), dict) else ""
    if minimum_version and not re.fullmatch(r"\d+\.\d+\.\d+", minimum_version):
        issues.append({"code": "invalid_minimum_version"})
    normalized = {
        "template_id": template_id,
        "name": _clean(manifest.get("name") or template_id),
        "version": version,
        "description": _clean(manifest.get("description")),
        "author": deepcopy(manifest.get("author", {})) if isinstance(manifest.get("author", {}), dict) else {},
        "license": license_id,
        "entrypoint": entrypoint,
        "files": normalized_files,
        "compatibility": deepcopy(manifest.get("compatibility", {})) if isinstance(manifest.get("compatibility", {}), dict) else {},
        "tags": sorted({_clean(item) for item in manifest.get("tags", []) if _clean(item)}),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "template_manifest_validation",
        "valid": not issues,
        "issues": issues,
        "issue_count": len(issues),
        "manifest": normalized,
        "manifest_fingerprint": manifest_fingerprint(normalized),
    }


def verify_template_trust(
    template_validation: dict[str, Any] | str,
    publisher_id: str,
    publisher_digest: str,
    trust_policy: dict[str, Any] | str,
) -> dict[str, Any]:
    validation = _mapping(template_validation, "template_validation")
    policy = _mapping(trust_policy, "trust_policy")
    publisher = slugify(publisher_id, "publisher")
    allowlist = {slugify(item, "publisher") for item in policy.get("allowed_publishers", [])}
    denied = {slugify(item, "publisher") for item in policy.get("denied_publishers", [])}
    expected_digests = policy.get("publisher_digests", {}) if isinstance(policy.get("publisher_digests", {}), dict) else {}
    issues: list[dict[str, Any]] = []
    if not validation.get("valid"):
        issues.append({"code": "invalid_template_manifest"})
    if publisher in denied:
        issues.append({"code": "publisher_denied", "publisher_id": publisher})
    if allowlist and publisher not in allowlist:
        issues.append({"code": "publisher_not_allowlisted", "publisher_id": publisher})
    digest = _clean(publisher_digest).lower()
    expected = _clean(expected_digests.get(publisher)).lower()
    if expected and digest != expected:
        issues.append({"code": "publisher_digest_mismatch", "expected": expected, "actual": digest})
    if policy.get("require_digest", True) and not re.fullmatch(r"[0-9a-f]{64}", digest):
        issues.append({"code": "missing_or_invalid_publisher_digest"})
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "template_trust_report",
        "trusted": not issues,
        "publisher_id": publisher,
        "publisher_digest": digest,
        "issues": issues,
        "issue_count": len(issues),
        "template_fingerprint": validation.get("manifest_fingerprint"),
    }


FAULT_TYPES = {"timeout", "worker_loss", "rate_limit", "oom", "corrupt_output", "network_partition", "queue_conflict"}


def build_fault_injection_plan(
    generation_queue: dict[str, Any] | str,
    scenarios: list[dict[str, Any]] | str,
    master_seed: int = 0,
) -> dict[str, Any]:
    """Build a deterministic dry-run fault plan; this function never executes destructive actions."""
    queue = _mapping(generation_queue, "generation_queue")
    scenario_rows = _list(scenarios, "scenarios")
    task_ids = {item.get("task_id") for item in queue.get("tasks", []) if isinstance(item, dict)}
    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(scenario_rows, start=1):
        if not isinstance(raw, dict):
            issues.append({"index": index, "code": "invalid_scenario"})
            continue
        fault_type = _clean(raw.get("fault_type")).lower()
        if fault_type not in FAULT_TYPES:
            issues.append({"index": index, "code": "unknown_fault_type", "fault_type": fault_type})
            continue
        target_task_id = _clean(raw.get("task_id")) or None
        if target_task_id and target_task_id not in task_ids:
            issues.append({"index": index, "code": "unknown_task", "task_id": target_task_id})
            continue
        probability = float(raw.get("probability", 1.0) or 0)
        if probability < 0 or probability > 1:
            issues.append({"index": index, "code": "invalid_probability"})
            continue
        deterministic_value = int(_sha([int(master_seed), index, fault_type, target_task_id], 16), 16) / float(16**16 - 1)
        triggered = deterministic_value < probability
        normalized.append({
            "scenario_id": f"fault-{index:03d}-{_sha(raw, 8)}",
            "fault_type": fault_type,
            "task_id": target_task_id,
            "worker_id": _clean(raw.get("worker_id")) or None,
            "at_attempt": max(1, int(raw.get("at_attempt", 1) or 1)),
            "probability": probability,
            "deterministic_value": round(deterministic_value, 8),
            "triggered": triggered,
            "expected_recovery": _clean(raw.get("expected_recovery")) or None,
            "parameters": deepcopy(raw.get("parameters", {})) if isinstance(raw.get("parameters", {}), dict) else {},
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "fault_injection_plan",
        "queue_id": queue.get("queue_id"),
        "queue_revision": queue.get("revision"),
        "master_seed": int(master_seed),
        "scenarios": normalized,
        "scenario_count": len(normalized),
        "triggered_count": sum(1 for item in normalized if item["triggered"]),
        "issues": issues,
        "valid": not issues,
        "dry_run_only": True,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def evaluate_fault_recovery(
    fault_plan: dict[str, Any] | str,
    observed_events: list[dict[str, Any]] | str,
) -> dict[str, Any]:
    plan = _mapping(fault_plan, "fault_plan")
    events = _list(observed_events, "observed_events")
    results: list[dict[str, Any]] = []
    for scenario in plan.get("scenarios", []):
        if not scenario.get("triggered"):
            results.append({"scenario_id": scenario.get("scenario_id"), "status": "not_triggered", "passed": True})
            continue
        matching = [event for event in events if isinstance(event, dict) and event.get("scenario_id") == scenario.get("scenario_id")]
        expected = scenario.get("expected_recovery")
        recovered = any(event.get("recovery_action") == expected and event.get("status") in {"recovered", "passed"} for event in matching) if expected else bool(matching)
        results.append({
            "scenario_id": scenario.get("scenario_id"),
            "fault_type": scenario.get("fault_type"),
            "expected_recovery": expected,
            "observed_event_count": len(matching),
            "status": "passed" if recovered else "failed",
            "passed": recovered,
        })
    failures = [item for item in results if not item["passed"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "fault_recovery_report",
        "passed": not failures,
        "results": results,
        "scenario_count": len(results),
        "failure_count": len(failures),
        "failures": failures,
    }


def build_replay_manifest(
    run_snapshot: dict[str, Any] | str,
    generation_queue: dict[str, Any] | str,
    outputs: list[dict[str, Any]] | str,
) -> dict[str, Any]:
    snapshot = _mapping(run_snapshot, "run_snapshot")
    queue = _mapping(generation_queue, "generation_queue")
    output_rows = _list(outputs, "outputs")
    tasks = [item for item in queue.get("tasks", []) if isinstance(item, dict)]
    task_records = []
    for task in sorted(tasks, key=lambda item: item.get("task_id", "")):
        task_records.append({
            "task_id": task.get("task_id"),
            "shot_id": task.get("shot_id"),
            "seed": task.get("seed"),
            "take_index": task.get("take_index"),
            "task_fingerprint": task.get("task_fingerprint") or manifest_fingerprint(task),
        })
    normalized_outputs = []
    for item in output_rows:
        if not isinstance(item, dict):
            continue
        normalized_outputs.append({
            "task_id": item.get("task_id"),
            "shot_id": item.get("shot_id"),
            "sha256": _clean(item.get("sha256")) or None,
            "output_fingerprint": item.get("output_fingerprint") or manifest_fingerprint(item.get("output", item)),
        })
    normalized_outputs.sort(key=lambda item: (str(item.get("task_id")), str(item.get("shot_id"))))
    replay = {
        "schema_version": SCHEMA_VERSION,
        "type": "replay_manifest",
        "run_snapshot_fingerprint": snapshot.get("fingerprint") or manifest_fingerprint(snapshot),
        "queue_id": queue.get("queue_id"),
        "queue_revision": queue.get("revision"),
        "queue_fingerprint": queue.get("fingerprint") or manifest_fingerprint(queue),
        "tasks": task_records,
        "outputs": normalized_outputs,
        "task_count": len(task_records),
        "output_count": len(normalized_outputs),
    }
    replay["replay_fingerprint"] = manifest_fingerprint(replay)
    return replay


def compare_replay_manifests(expected: dict[str, Any] | str, actual: dict[str, Any] | str) -> dict[str, Any]:
    expected_obj = _mapping(expected, "expected")
    actual_obj = _mapping(actual, "actual")
    differences: list[dict[str, Any]] = []
    scalar_fields = ["run_snapshot_fingerprint", "queue_id", "task_count", "output_count"]
    for field in scalar_fields:
        if expected_obj.get(field) != actual_obj.get(field):
            differences.append({"field": field, "expected": expected_obj.get(field), "actual": actual_obj.get(field)})
    expected_tasks = {item.get("task_id"): item for item in expected_obj.get("tasks", []) if isinstance(item, dict)}
    actual_tasks = {item.get("task_id"): item for item in actual_obj.get("tasks", []) if isinstance(item, dict)}
    for task_id in sorted(set(expected_tasks) | set(actual_tasks)):
        if expected_tasks.get(task_id) != actual_tasks.get(task_id):
            differences.append({"field": f"tasks.{task_id}", "expected": expected_tasks.get(task_id), "actual": actual_tasks.get(task_id)})
    expected_outputs = {item.get("task_id"): item for item in expected_obj.get("outputs", []) if isinstance(item, dict)}
    actual_outputs = {item.get("task_id"): item for item in actual_obj.get("outputs", []) if isinstance(item, dict)}
    for task_id in sorted(set(expected_outputs) | set(actual_outputs)):
        if expected_outputs.get(task_id) != actual_outputs.get(task_id):
            differences.append({"field": f"outputs.{task_id}", "expected": expected_outputs.get(task_id), "actual": actual_outputs.get(task_id)})
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "replay_comparison",
        "deterministic": not differences,
        "difference_count": len(differences),
        "differences": differences,
        "expected_fingerprint": expected_obj.get("replay_fingerprint") or manifest_fingerprint(expected_obj),
        "actual_fingerprint": actual_obj.get("replay_fingerprint") or manifest_fingerprint(actual_obj),
    }


def evaluate_generation_gate(
    collaboration: dict[str, Any] | str,
    approval_records: list[dict[str, Any]] | str,
    lock_state: dict[str, Any] | str | None = None,
    compatibility_matrix: dict[str, Any] | str | None = None,
    audit_verification: dict[str, Any] | str | None = None,
    required_resource_ids: list[str] | str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Combine collaboration controls into a single pre-generation release gate."""
    manifest = _mapping(collaboration, "collaboration")
    approvals = _list(approval_records, "approval_records")
    required = {slugify(item, "item") for item in _list(required_resource_ids or [], "required_resource_ids")}
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    approved_ids: set[str] = set()
    for raw in approvals:
        if not isinstance(raw, dict):
            continue
        resource_id = slugify(raw.get("resource_id"), "item")
        if raw.get("state") == "approved":
            approved_ids.add(resource_id)
        elif resource_id in required:
            blockers.append({"code": "resource_not_approved", "resource_id": resource_id, "state": raw.get("state")})
    for missing in sorted(required - approved_ids):
        if not any(item.get("resource_id") == missing for item in blockers):
            blockers.append({"code": "missing_approval", "resource_id": missing})
    if lock_state is not None:
        locks = _mapping(lock_state, "lock_state")
        stamp = _now_ms(now_ms)
        for lock in locks.get("locks", []):
            if isinstance(lock, dict) and int(lock.get("expires_at_ms", 0)) > stamp:
                blockers.append({"code": "active_edit_lock", "resource_id": lock.get("resource_id"), "holder_id": lock.get("holder_id")})
    if compatibility_matrix is not None:
        matrix = _mapping(compatibility_matrix, "compatibility_matrix")
        if int(matrix.get("compatible_count", 0)) <= 0:
            blockers.append({"code": "no_compatible_environment"})
        elif not matrix.get("all_compatible", False):
            warnings.append({"code": "some_environments_incompatible", "compatible_count": matrix.get("compatible_count")})
    if audit_verification is not None:
        verification = _mapping(audit_verification, "audit_verification")
        if not verification.get("valid", False):
            blockers.append({"code": "audit_chain_invalid", "issue_count": verification.get("issue_count", 0)})
    inactive_owners = [member["member_id"] for member in manifest.get("members", []) if member.get("role") == "owner" and not member.get("active", True)]
    if inactive_owners:
        blockers.append({"code": "owner_inactive", "member_ids": inactive_owners})
    score = max(0, 100 - len(blockers) * 25 - len(warnings) * 5)
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "generation_release_gate",
        "project_id": manifest.get("project_id"),
        "ready": not blockers,
        "score": score,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "warnings": warnings,
        "warning_count": len(warnings),
        "approved_resource_ids": sorted(approved_ids),
        "required_resource_ids": sorted(required),
    }


def build_collaboration_dashboard(
    collaboration: dict[str, Any] | str,
    lock_state: dict[str, Any] | str | None = None,
    approval_records: list[dict[str, Any]] | str | None = None,
    change_requests: list[dict[str, Any]] | str | None = None,
    worker_registry: dict[str, Any] | str | None = None,
    generation_gate: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    manifest = _mapping(collaboration, "collaboration")
    locks = _mapping(lock_state or {"locks": []}, "lock_state")
    approvals = _list(approval_records or [], "approval_records")
    changes = _list(change_requests or [], "change_requests")
    workers = _mapping(worker_registry or {"workers": []}, "worker_registry")
    gate = _mapping(generation_gate or {"ready": False, "score": 0}, "generation_gate")
    approval_counts: dict[str, int] = {state: 0 for state in sorted(APPROVAL_STATES)}
    for record in approvals:
        if isinstance(record, dict):
            state = _clean(record.get("state"))
            approval_counts[state] = approval_counts.get(state, 0) + 1
    change_counts: dict[str, int] = {}
    for request in changes:
        if isinstance(request, dict):
            status = _clean(request.get("status")) or "unknown"
            change_counts[status] = change_counts.get(status, 0) + 1
    worker_counts: dict[str, int] = {}
    available_slots = 0
    for worker in workers.get("workers", []):
        if not isinstance(worker, dict):
            continue
        state = _clean(worker.get("state")) or "unknown"
        worker_counts[state] = worker_counts.get(state, 0) + 1
        if state in {"online", "busy"}:
            available_slots += max(0, int(worker.get("capacity", 1)) - int(worker.get("active_tasks", 0)))
    attention: list[dict[str, Any]] = []
    if approval_counts.get("changes_requested", 0):
        attention.append({"code": "approval_changes_requested", "count": approval_counts["changes_requested"]})
    if change_counts.get("open", 0):
        attention.append({"code": "open_change_requests", "count": change_counts["open"]})
    if worker_counts.get("stale", 0):
        attention.append({"code": "stale_workers", "count": worker_counts["stale"]})
    if int(gate.get("blocker_count", 0)):
        attention.append({"code": "generation_gate_blocked", "count": gate.get("blocker_count")})
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "collaboration_dashboard",
        "project_id": manifest.get("project_id"),
        "member_count": manifest.get("member_count", len(manifest.get("members", []))),
        "active_lock_count": len(locks.get("locks", [])),
        "approval_counts": approval_counts,
        "change_request_counts": dict(sorted(change_counts.items())),
        "worker_counts": dict(sorted(worker_counts.items())),
        "available_worker_slots": available_slots,
        "generation_ready": bool(gate.get("ready", False)),
        "generation_score": int(gate.get("score", 0) or 0),
        "attention": attention,
        "attention_count": len(attention),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result
