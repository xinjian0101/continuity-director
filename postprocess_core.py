from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from continuity_core import ContinuityValidationError, SCHEMA_VERSION, manifest_fingerprint, slugify
from production_core import make_issue


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


def _file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _fraction(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return None
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator_value = float(denominator)
            return float(numerator) / denominator_value if denominator_value else None
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def normalize_ffprobe_payload(payload: dict[str, Any] | str, source: str = "") -> dict[str, Any]:
    """Normalize ffprobe JSON into a stable, provider-neutral media description."""
    obj = _mapping(payload, "ffprobe_payload")
    streams = obj.get("streams", [])
    if not isinstance(streams, list):
        raise ContinuityValidationError("ffprobe_payload.streams 必须是数组")
    format_data = obj.get("format", {}) if isinstance(obj.get("format", {}), dict) else {}
    video_streams: list[dict[str, Any]] = []
    audio_streams: list[dict[str, Any]] = []
    subtitle_streams: list[dict[str, Any]] = []
    for raw in streams:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("codec_type", "")).strip().lower()
        common = {
            "index": int(raw.get("index", 0)),
            "codec": str(raw.get("codec_name", "")).strip() or None,
            "profile": str(raw.get("profile", "")).strip() or None,
            "duration_seconds": _fraction(raw.get("duration")),
            "bit_rate": int(raw["bit_rate"]) if str(raw.get("bit_rate", "")).isdigit() else None,
            "tags": deepcopy(raw.get("tags", {})) if isinstance(raw.get("tags", {}), dict) else {},
        }
        if kind == "video":
            fps = _fraction(raw.get("avg_frame_rate")) or _fraction(raw.get("r_frame_rate"))
            frames = int(raw["nb_frames"]) if str(raw.get("nb_frames", "")).isdigit() else None
            video_streams.append({
                **common,
                "width": int(raw.get("width", 0) or 0),
                "height": int(raw.get("height", 0) or 0),
                "fps": round(fps, 6) if fps is not None else None,
                "frame_count": frames,
                "pixel_format": str(raw.get("pix_fmt", "")).strip() or None,
                "color_space": str(raw.get("color_space", "")).strip() or None,
                "color_transfer": str(raw.get("color_transfer", "")).strip() or None,
                "rotation": int((raw.get("tags") or {}).get("rotate", 0) or 0) if isinstance(raw.get("tags"), dict) else 0,
            })
        elif kind == "audio":
            audio_streams.append({
                **common,
                "sample_rate": int(raw["sample_rate"]) if str(raw.get("sample_rate", "")).isdigit() else None,
                "channels": int(raw.get("channels", 0) or 0),
                "channel_layout": str(raw.get("channel_layout", "")).strip() or None,
            })
        elif kind == "subtitle":
            subtitle_streams.append(common)
    duration = _fraction(format_data.get("duration"))
    size_bytes = int(format_data["size"]) if str(format_data.get("size", "")).isdigit() else None
    bit_rate = int(format_data["bit_rate"]) if str(format_data.get("bit_rate", "")).isdigit() else None
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "media_probe",
        "source": str(source or format_data.get("filename", "")).strip(),
        "format_name": str(format_data.get("format_name", "")).strip() or None,
        "format_long_name": str(format_data.get("format_long_name", "")).strip() or None,
        "duration_seconds": round(duration, 6) if duration is not None else None,
        "size_bytes": size_bytes,
        "bit_rate": bit_rate,
        "video_streams": video_streams,
        "audio_streams": audio_streams,
        "subtitle_streams": subtitle_streams,
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "subtitle_stream_count": len(subtitle_streams),
    }
    primary = video_streams[0] if video_streams else None
    result["primary_video"] = deepcopy(primary)
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def probe_media_file(
    path: str | os.PathLike[str],
    ffprobe_binary: str = "ffprobe",
    timeout_seconds: int = 30,
    include_file_hash: bool = False,
) -> dict[str, Any]:
    """Run local ffprobe safely without a shell. ffprobe is optional and discovered at runtime."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ContinuityValidationError(f"媒体文件不存在：{source}")
    binary = shutil.which(ffprobe_binary) if not Path(ffprobe_binary).is_file() else str(Path(ffprobe_binary).resolve())
    if not binary:
        raise ContinuityValidationError("未找到 ffprobe；请安装 FFmpeg 或传入 ffprobe 可执行文件路径")
    command = [
        binary,
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(source),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=max(1, int(timeout_seconds)), check=False)
    except subprocess.TimeoutExpired as exc:
        raise ContinuityValidationError(f"ffprobe 超时：{timeout_seconds}s") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "ffprobe failed").strip()[-2000:]
        raise ContinuityValidationError(f"ffprobe 失败：{message}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContinuityValidationError("ffprobe 返回了无效 JSON") from exc
    result = normalize_ffprobe_payload(payload, str(source))
    result["probe_command"] = command[:-1] + ["<media-file>"]
    if include_file_hash:
        result["sha256"] = _file_sha256(source)
    result["fingerprint"] = manifest_fingerprint(result)
    return result

FRAME_FORMATS = {"png", "jpg", "jpeg", "webp"}


def build_frame_extraction_plan(
    media_probe: dict[str, Any] | str,
    output_dir: str | os.PathLike[str],
    mode: str = "boundary",
    sample_count: int = 2,
    custom_timestamps: list[float] | str | None = None,
    image_format: str = "png",
    filename_prefix: str = "frame",
) -> dict[str, Any]:
    """Create a deterministic frame extraction plan without touching the media file."""
    probe = _mapping(media_probe, "media_probe")
    if probe.get("type") != "media_probe":
        raise ContinuityValidationError("media_probe 类型错误")
    source = str(probe.get("source", "")).strip()
    if not source:
        raise ContinuityValidationError("media_probe 缺少 source")
    duration = probe.get("duration_seconds")
    if duration is None or float(duration) <= 0:
        raise ContinuityValidationError("媒体时长无效，无法规划抽帧")
    duration_value = float(duration)
    kind = str(mode).strip().lower()
    if kind not in {"boundary", "uniform", "custom"}:
        raise ContinuityValidationError("mode 必须是 boundary/uniform/custom")
    count = max(1, min(1000, int(sample_count)))
    extension = str(image_format).strip().lower().lstrip(".")
    if extension not in FRAME_FORMATS:
        raise ContinuityValidationError(f"不支持的图片格式：{extension}")
    fps = None
    if isinstance(probe.get("primary_video"), dict):
        fps = probe["primary_video"].get("fps")
    frame_margin = 1.0 / float(fps) if fps else min(0.04, duration_value / 1000)
    final_timestamp = max(0.0, duration_value - frame_margin)
    if kind == "boundary":
        timestamps = [0.0] if count == 1 else [0.0, final_timestamp]
        if count > 2:
            middle = [duration_value * index / (count - 1) for index in range(1, count - 1)]
            timestamps = [0.0, *middle, final_timestamp]
    elif kind == "uniform":
        timestamps = [duration_value * (index + 1) / (count + 1) for index in range(count)]
    else:
        raw = _list(custom_timestamps, "custom_timestamps")
        timestamps = []
        for value in raw:
            try:
                timestamp = float(value)
            except (TypeError, ValueError) as exc:
                raise ContinuityValidationError("custom_timestamps 必须是数字数组") from exc
            if timestamp < 0 or timestamp > duration_value:
                raise ContinuityValidationError(f"抽帧时间超出媒体范围：{timestamp}")
            timestamps.append(min(timestamp, final_timestamp))
        if not timestamps:
            raise ContinuityValidationError("custom 模式必须提供至少一个时间点")
    timestamps = sorted(set(round(value, 6) for value in timestamps))
    target_dir = Path(output_dir).expanduser().resolve()
    prefix = slugify(filename_prefix, "frame")
    frames = []
    for index, timestamp in enumerate(timestamps, start=1):
        filename = f"{prefix}-{index:04d}-{int(round(timestamp * 1000)):010d}ms.{extension}"
        frames.append({
            "frame_id": f"frame-{index:04d}-{_sha([source, timestamp], 8)}",
            "timestamp_seconds": timestamp,
            "output_path": str(target_dir / filename),
            "format": extension,
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "frame_extraction_plan",
        "source": source,
        "source_probe_fingerprint": probe.get("fingerprint"),
        "mode": kind,
        "output_dir": str(target_dir),
        "frames": frames,
        "frame_count": len(frames),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def execute_frame_extraction(
    extraction_plan: dict[str, Any] | str,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: int = 120,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Execute a validated extraction plan through FFmpeg without shell interpolation."""
    plan = _mapping(extraction_plan, "frame_extraction_plan")
    if plan.get("type") != "frame_extraction_plan":
        raise ContinuityValidationError("frame_extraction_plan 类型错误")
    source = Path(str(plan.get("source", ""))).expanduser().resolve()
    if not source.is_file():
        raise ContinuityValidationError(f"媒体文件不存在：{source}")
    binary = shutil.which(ffmpeg_binary) if not Path(ffmpeg_binary).is_file() else str(Path(ffmpeg_binary).resolve())
    if not binary:
        raise ContinuityValidationError("未找到 ffmpeg；请安装 FFmpeg 或传入可执行文件路径")
    extracted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for frame in plan.get("frames", []):
        if not isinstance(frame, dict):
            continue
        target = Path(str(frame.get("output_path", ""))).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            failures.append({"frame_id": frame.get("frame_id"), "error": "output_exists", "path": str(target)})
            continue
        command = [
            binary,
            "-hide_banner", "-loglevel", "error",
            "-ss", f"{float(frame.get('timestamp_seconds', 0.0)):.6f}",
            "-i", str(source),
            "-frames:v", "1",
            "-y" if overwrite else "-n",
            str(target),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=max(1, int(timeout_seconds)), check=False)
        except subprocess.TimeoutExpired:
            failures.append({"frame_id": frame.get("frame_id"), "error": "timeout", "path": str(target)})
            continue
        if completed.returncode != 0 or not target.is_file():
            failures.append({
                "frame_id": frame.get("frame_id"),
                "error": "ffmpeg_failed",
                "path": str(target),
                "detail": (completed.stderr or completed.stdout or "").strip()[-1000:],
            })
            continue
        extracted.append({
            **deepcopy(frame),
            "size_bytes": target.stat().st_size,
            "sha256": _file_sha256(target),
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "frame_extraction_result",
        "plan_fingerprint": plan.get("fingerprint"),
        "source": str(source),
        "frames": extracted,
        "extracted_count": len(extracted),
        "failed_count": len(failures),
        "failures": failures,
        "complete": not failures and len(extracted) == int(plan.get("frame_count", 0)),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result

DEFAULT_TECHNICAL_POLICY = {
    "min_width": 512,
    "min_height": 512,
    "min_fps": 20.0,
    "max_fps": 120.0,
    "min_duration_seconds": 0.1,
    "duration_tolerance_seconds": 0.25,
    "require_video": True,
    "require_audio": False,
    "allowed_video_codecs": [],
    "allowed_pixel_formats": [],
    "max_black_frame_ratio": 0.02,
    "max_freeze_ratio": 0.10,
    "max_decode_errors": 0,
}


def evaluate_technical_quality(
    media_probe: dict[str, Any] | str,
    policy: dict[str, Any] | str | None = None,
    expected_duration_seconds: float | None = None,
    expected_fps: float | None = None,
    analysis_metrics: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Evaluate container/stream metadata and optional detector metrics against a deterministic policy."""
    probe = _mapping(media_probe, "media_probe")
    if probe.get("type") != "media_probe":
        raise ContinuityValidationError("media_probe 类型错误")
    settings = deepcopy(DEFAULT_TECHNICAL_POLICY)
    if policy:
        settings.update(_mapping(policy, "technical_policy"))
    metrics = _mapping(analysis_metrics, "analysis_metrics") if analysis_metrics else {}
    issues: list[dict[str, Any]] = []
    deductions = 0.0
    primary = probe.get("primary_video") if isinstance(probe.get("primary_video"), dict) else None
    if bool(settings.get("require_video", True)) and not primary:
        issues.append(make_issue("VIDEO_STREAM_MISSING", "error", "video", "媒体缺少视频流"))
        deductions += 70
    if primary:
        width = int(primary.get("width", 0) or 0)
        height = int(primary.get("height", 0) or 0)
        fps = primary.get("fps")
        if width < int(settings.get("min_width", 0)) or height < int(settings.get("min_height", 0)):
            issues.append(make_issue("RESOLUTION_TOO_LOW", "error", "video.resolution", "视频分辨率低于门槛", width=width, height=height))
            deductions += 25
        if fps is None:
            issues.append(make_issue("FPS_UNKNOWN", "warning", "video.fps", "无法确认视频帧率"))
            deductions += 8
        else:
            fps_value = float(fps)
            if fps_value < float(settings.get("min_fps", 0)) or fps_value > float(settings.get("max_fps", 1e9)):
                issues.append(make_issue("FPS_OUT_OF_RANGE", "error", "video.fps", "视频帧率超出允许范围", fps=fps_value))
                deductions += 20
            if expected_fps is not None and abs(fps_value - float(expected_fps)) > 0.01:
                issues.append(make_issue("FPS_MISMATCH", "warning", "video.fps", "视频帧率与项目设置不一致", expected=expected_fps, actual=fps_value))
                deductions += 8
        allowed_codecs = [str(item).lower() for item in settings.get("allowed_video_codecs", []) if str(item).strip()]
        if allowed_codecs and str(primary.get("codec", "")).lower() not in allowed_codecs:
            issues.append(make_issue("VIDEO_CODEC_NOT_ALLOWED", "error", "video.codec", "视频编码不在允许列表", codec=primary.get("codec")))
            deductions += 20
        allowed_formats = [str(item).lower() for item in settings.get("allowed_pixel_formats", []) if str(item).strip()]
        if allowed_formats and str(primary.get("pixel_format", "")).lower() not in allowed_formats:
            issues.append(make_issue("PIXEL_FORMAT_NOT_ALLOWED", "error", "video.pixel_format", "像素格式不在允许列表", pixel_format=primary.get("pixel_format")))
            deductions += 15
    duration = probe.get("duration_seconds")
    if duration is None or float(duration) < float(settings.get("min_duration_seconds", 0.1)):
        issues.append(make_issue("DURATION_INVALID", "error", "format.duration", "视频时长无效或过短", duration=duration))
        deductions += 30
    elif expected_duration_seconds is not None:
        delta = abs(float(duration) - float(expected_duration_seconds))
        if delta > float(settings.get("duration_tolerance_seconds", 0.25)):
            issues.append(make_issue("DURATION_MISMATCH", "warning", "format.duration", "视频时长与镜头计划不一致", expected=expected_duration_seconds, actual=duration, delta=round(delta, 6)))
            deductions += min(20, 5 + delta * 5)
    if bool(settings.get("require_audio", False)) and int(probe.get("audio_stream_count", 0)) < 1:
        issues.append(make_issue("AUDIO_STREAM_MISSING", "error", "audio", "策略要求音轨，但媒体缺少音频流"))
        deductions += 15
    detector_rules = (
        ("black_frame_ratio", "max_black_frame_ratio", "BLACK_FRAME_RATIO_HIGH", "黑帧比例过高", 20),
        ("freeze_ratio", "max_freeze_ratio", "FREEZE_RATIO_HIGH", "冻结画面比例过高", 20),
        ("decode_errors", "max_decode_errors", "DECODE_ERRORS", "检测到解码错误", 30),
    )
    for metric_name, policy_name, code, message, penalty in detector_rules:
        if metric_name not in metrics:
            continue
        actual = float(metrics.get(metric_name, 0))
        maximum = float(settings.get(policy_name, 0))
        if actual > maximum:
            issues.append(make_issue(code, "error", f"analysis.{metric_name}", message, actual=actual, maximum=maximum))
            deductions += penalty
    score = round(max(0.0, 100.0 - deductions), 3)
    error_count = sum(1 for item in issues if item.get("severity") == "error")
    warning_count = sum(1 for item in issues if item.get("severity") == "warning")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "technical_qc_report",
        "source": probe.get("source"),
        "media_probe_fingerprint": probe.get("fingerprint"),
        "policy": settings,
        "analysis_metrics": metrics,
        "score": score,
        "decision": "fail" if error_count else ("warning" if warning_count else "pass"),
        "issues": issues,
        "error_count": error_count,
        "warning_count": warning_count,
        "passed": error_count == 0,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result

METRIC_SCALES = {"0-1", "0-100", "distance-0-1", "distance-0-100"}


def _lookup_path(data: Any, path: str) -> Any:
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ContinuityValidationError(f"外部指标字段不存在：{path}")
    return current


def normalize_external_metrics(
    adapter_spec: dict[str, Any] | str,
    payload: dict[str, Any] | str,
) -> dict[str, Any]:
    """Map external model output to 0-100 quality metrics using a declarative adapter."""
    spec = _mapping(adapter_spec, "adapter_spec")
    data = _mapping(payload, "metric_payload")
    adapter_id = slugify(spec.get("adapter_id") or spec.get("name"), "metric-adapter")
    definitions = spec.get("metrics")
    if not isinstance(definitions, dict) or not definitions:
        raise ContinuityValidationError("adapter_spec.metrics 必须是非空对象")
    normalized: dict[str, float] = {}
    evidence: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for metric_name, raw_rule in definitions.items():
        name = slugify(str(metric_name), "metric").replace("-", "_")
        if not isinstance(raw_rule, dict):
            raise ContinuityValidationError(f"metrics.{metric_name} 必须是对象")
        path = str(raw_rule.get("path", metric_name)).strip()
        scale = str(raw_rule.get("scale", "0-1")).strip().lower()
        if scale not in METRIC_SCALES:
            raise ContinuityValidationError(f"metrics.{metric_name}.scale 不受支持：{scale}")
        required = bool(raw_rule.get("required", True))
        try:
            raw_value = float(_lookup_path(data, path))
        except (ContinuityValidationError, TypeError, ValueError) as exc:
            if required:
                issues.append(make_issue("EXTERNAL_METRIC_MISSING", "error", path, "外部指标缺失或不是数字", metric=name, error=str(exc)))
            else:
                issues.append(make_issue("EXTERNAL_METRIC_OPTIONAL_MISSING", "warning", path, "可选外部指标缺失", metric=name))
            continue
        if not math.isfinite(raw_value):
            issues.append(make_issue("EXTERNAL_METRIC_NOT_FINITE", "error", path, "外部指标不是有限数字", metric=name))
            continue
        if scale == "0-1":
            score = raw_value * 100.0
        elif scale == "0-100":
            score = raw_value
        elif scale == "distance-0-1":
            score = (1.0 - raw_value) * 100.0
        else:
            score = 100.0 - raw_value
        minimum = raw_rule.get("min")
        maximum = raw_rule.get("max")
        if minimum is not None or maximum is not None:
            low = float(minimum if minimum is not None else 0.0)
            high = float(maximum if maximum is not None else 1.0)
            if high <= low:
                raise ContinuityValidationError(f"metrics.{metric_name} 的 min/max 无效")
            score = (raw_value - low) / (high - low) * 100.0
            if bool(raw_rule.get("invert", False)):
                score = 100.0 - score
        score = round(max(0.0, min(100.0, score)), 3)
        normalized[name] = score
        evidence[name] = {"path": path, "raw_value": raw_value, "scale": scale, "score": score}
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "normalized_quality_metrics",
        "adapter_id": adapter_id,
        "adapter_version": str(spec.get("version", "1")).strip(),
        "metrics": normalized,
        "evidence": evidence,
        "issues": issues,
        "valid": error_count == 0,
        "error_count": error_count,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result

DEFAULT_BOUNDARY_THRESHOLDS = {
    "identity_similarity": 80.0,
    "composition_match": 65.0,
    "lighting_match": 70.0,
    "color_match": 70.0,
    "motion_continuity": 65.0,
    "overall": 72.0,
}


def evaluate_boundary_continuity(
    previous_shot: dict[str, Any] | str,
    next_shot: dict[str, Any] | str,
    previous_frames: dict[str, Any] | str,
    next_frames: dict[str, Any] | str,
    metrics: dict[str, Any] | str,
    thresholds: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Evaluate the last frame of one shot against the first frame of the next shot."""
    prev = _mapping(previous_shot, "previous_shot")
    nxt = _mapping(next_shot, "next_shot")
    prev_result = _mapping(previous_frames, "previous_frames")
    next_result = _mapping(next_frames, "next_frames")
    score_data = _mapping(metrics, "boundary_metrics")
    limits = deepcopy(DEFAULT_BOUNDARY_THRESHOLDS)
    if thresholds:
        limits.update(_mapping(thresholds, "boundary_thresholds"))
    prev_items = prev_result.get("frames", [])
    next_items = next_result.get("frames", [])
    if not isinstance(prev_items, list) or not prev_items:
        raise ContinuityValidationError("previous_frames 不包含已抽取帧")
    if not isinstance(next_items, list) or not next_items:
        raise ContinuityValidationError("next_frames 不包含已抽取帧")
    prev_boundary = max(prev_items, key=lambda item: float(item.get("timestamp_seconds", 0)))
    next_boundary = min(next_items, key=lambda item: float(item.get("timestamp_seconds", 0)))
    dimensions = []
    issues: list[dict[str, Any]] = []
    weights = {
        "identity_similarity": 3.0,
        "composition_match": 1.5,
        "lighting_match": 1.5,
        "color_match": 1.0,
        "motion_continuity": 1.5,
    }
    weighted_sum = 0.0
    total_weight = 0.0
    for name, weight in weights.items():
        if name not in score_data:
            issues.append(make_issue("BOUNDARY_METRIC_MISSING", "warning", f"metrics.{name}", "边界连续性指标缺失", metric=name))
            continue
        try:
            score = max(0.0, min(100.0, float(score_data[name])))
        except (TypeError, ValueError) as exc:
            raise ContinuityValidationError(f"边界指标 {name} 必须是数字") from exc
        threshold = float(limits.get(name, 0))
        passed = score >= threshold
        dimensions.append({"dimension": name, "score": round(score, 3), "threshold": threshold, "weight": weight, "passed": passed})
        weighted_sum += score * weight
        total_weight += weight
        if not passed:
            severity = "error" if name == "identity_similarity" else "warning"
            issues.append(make_issue("BOUNDARY_DIMENSION_FAILED", severity, f"metrics.{name}", "镜头边界连续性指标未达标", metric=name, score=score, threshold=threshold))
    overall = round(weighted_sum / total_weight, 3) if total_weight else 0.0
    if overall < float(limits.get("overall", 72.0)):
        issues.append(make_issue("BOUNDARY_OVERALL_FAILED", "error", "metrics.overall", "镜头边界综合连续性未达标", score=overall, threshold=limits.get("overall")))
    previous_exit = str((prev.get("transition") or {}).get("exit_frame", prev.get("exit_frame", ""))).strip() if isinstance(prev.get("transition", {}), dict) else ""
    next_entry = str((nxt.get("transition") or {}).get("entry_frame", nxt.get("entry_frame", ""))).strip() if isinstance(nxt.get("transition", {}), dict) else ""
    if previous_exit and next_entry and previous_exit.casefold() != next_entry.casefold():
        issues.append(make_issue("BOUNDARY_DESCRIPTION_MISMATCH", "warning", "transition", "上一镜出场画面与下一镜入场画面描述不一致", previous_exit=previous_exit, next_entry=next_entry))
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "boundary_continuity_report",
        "previous_shot_id": prev.get("shot_id"),
        "next_shot_id": nxt.get("shot_id"),
        "previous_boundary_frame": deepcopy(prev_boundary),
        "next_boundary_frame": deepcopy(next_boundary),
        "dimensions": dimensions,
        "overall_score": overall,
        "thresholds": limits,
        "decision": "fail" if error_count else ("warning" if issues else "pass"),
        "passed": error_count == 0,
        "issues": issues,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result

ASSEMBLY_STRATEGIES = {"copy", "transcode"}


def build_sequence_assembly_plan(
    clips: list[dict[str, Any]] | str,
    output_path: str | os.PathLike[str],
    strategy: str = "transcode",
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    target_fps: float | None = None,
    metadata: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Build an ordered FFmpeg concat plan from selected shot takes."""
    items = _list(clips, "clips")
    if not items:
        raise ContinuityValidationError("clips 不能为空")
    mode = str(strategy).strip().lower()
    if mode not in ASSEMBLY_STRATEGIES:
        raise ContinuityValidationError("strategy 必须是 copy/transcode")
    normalized: list[dict[str, Any]] = []
    seen_shots: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"clips[{index}] 必须是对象")
        shot_id = slugify(raw.get("shot_id") or f"shot-{index + 1:04d}", f"shot-{index + 1:04d}")
        if shot_id in seen_shots:
            raise ContinuityValidationError(f"镜头重复：{shot_id}")
        seen_shots.add(shot_id)
        source_text = str(raw.get("path") or raw.get("source") or "").strip()
        if not source_text:
            raise ContinuityValidationError(f"clips[{index}] 缺少 path")
        source = Path(source_text).expanduser().resolve()
        trim_in = max(0.0, float(raw.get("trim_in_seconds", 0.0) or 0.0))
        trim_out_raw = raw.get("trim_out_seconds")
        trim_out = float(trim_out_raw) if trim_out_raw not in (None, "") else None
        if trim_out is not None and trim_out <= trim_in:
            raise ContinuityValidationError(f"clips[{index}] trim_out_seconds 必须大于 trim_in_seconds")
        normalized.append({
            "shot_id": shot_id,
            "source": str(source),
            "order": int(raw.get("order", index + 1)),
            "trim_in_seconds": round(trim_in, 6),
            "trim_out_seconds": round(trim_out, 6) if trim_out is not None else None,
            "expected_duration_seconds": raw.get("expected_duration_seconds"),
            "source_sha256": raw.get("sha256"),
        })
    normalized.sort(key=lambda item: (item["order"], item["shot_id"]))
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        target = target.with_suffix(".mp4")
    fps = None if target_fps in (None, 0, "") else float(target_fps)
    if fps is not None and (fps <= 0 or fps > 240):
        raise ContinuityValidationError("target_fps 必须在 0 到 240 之间")
    plan = {
        "schema_version": SCHEMA_VERSION,
        "type": "sequence_assembly_plan",
        "strategy": mode,
        "clips": normalized,
        "clip_count": len(normalized),
        "output_path": str(target),
        "video_codec": str(video_codec).strip() or "libx264",
        "audio_codec": str(audio_codec).strip() or "aac",
        "target_fps": fps,
        "metadata": _mapping(metadata, "metadata") if metadata else {},
    }
    plan["fingerprint"] = manifest_fingerprint(plan)
    return plan


def _concat_escape(path: str) -> str:
    return path.replace("'", "'\\''")


def execute_sequence_assembly(
    assembly_plan: dict[str, Any] | str,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: int = 1800,
    overwrite: bool = False,
    verify_sources: bool = True,
) -> dict[str, Any]:
    """Assemble selected takes with FFmpeg concat demuxer using a generated temporary list."""
    plan = _mapping(assembly_plan, "sequence_assembly_plan")
    if plan.get("type") != "sequence_assembly_plan":
        raise ContinuityValidationError("sequence_assembly_plan 类型错误")
    binary = shutil.which(ffmpeg_binary) if not Path(ffmpeg_binary).is_file() else str(Path(ffmpeg_binary).resolve())
    if not binary:
        raise ContinuityValidationError("未找到 ffmpeg")
    clips = plan.get("clips", [])
    if not isinstance(clips, list) or not clips:
        raise ContinuityValidationError("assembly_plan.clips 不能为空")
    source_errors = []
    lines: list[str] = []
    for clip in clips:
        source = Path(str(clip.get("source", ""))).expanduser().resolve()
        if not source.is_file():
            source_errors.append({"shot_id": clip.get("shot_id"), "error": "source_missing", "source": str(source)})
            continue
        expected_hash = str(clip.get("source_sha256") or "").strip().lower()
        if verify_sources and expected_hash and _file_sha256(source) != expected_hash:
            source_errors.append({"shot_id": clip.get("shot_id"), "error": "source_checksum_mismatch", "source": str(source)})
            continue
        lines.append(f"file '{_concat_escape(str(source))}'")
        if float(clip.get("trim_in_seconds", 0) or 0) > 0:
            lines.append(f"inpoint {float(clip['trim_in_seconds']):.6f}")
        if clip.get("trim_out_seconds") is not None:
            lines.append(f"outpoint {float(clip['trim_out_seconds']):.6f}")
    if source_errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "type": "sequence_assembly_result",
            "plan_fingerprint": plan.get("fingerprint"),
            "success": False,
            "output_path": plan.get("output_path"),
            "source_errors": source_errors,
            "error": "source_validation_failed",
        }
    target = Path(str(plan.get("output_path", ""))).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise ContinuityValidationError(f"输出文件已存在：{target}")
    fd, concat_path_text = tempfile.mkstemp(prefix="continuity-concat-", suffix=".txt", dir=str(target.parent))
    os.close(fd)
    concat_path = Path(concat_path_text)
    try:
        concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        command = [binary, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_path)]
        if plan.get("strategy") == "copy":
            command.extend(["-c", "copy"])
        else:
            command.extend(["-c:v", str(plan.get("video_codec", "libx264")), "-c:a", str(plan.get("audio_codec", "aac"))])
            if plan.get("target_fps"):
                command.extend(["-r", str(float(plan["target_fps"]))])
            command.extend(["-movflags", "+faststart"])
        command.extend(["-y" if overwrite else "-n", str(target)])
        started = time.time()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=max(1, int(timeout_seconds)), check=False)
        except subprocess.TimeoutExpired as exc:
            raise ContinuityValidationError(f"视频拼接超时：{timeout_seconds}s") from exc
        elapsed = round(time.time() - started, 3)
        success = completed.returncode == 0 and target.is_file()
        result = {
            "schema_version": SCHEMA_VERSION,
            "type": "sequence_assembly_result",
            "plan_fingerprint": plan.get("fingerprint"),
            "success": success,
            "output_path": str(target),
            "elapsed_seconds": elapsed,
            "clip_count": len(clips),
            "return_code": completed.returncode,
            "stderr": (completed.stderr or "").strip()[-4000:],
            "command": command[:-1] + ["<output-file>"],
        }
        if success:
            result["size_bytes"] = target.stat().st_size
            result["sha256"] = _file_sha256(target)
            result["media_probe"] = probe_media_file(target)
        result["fingerprint"] = manifest_fingerprint(result)
        return result
    finally:
        concat_path.unlink(missing_ok=True)


def create_version_snapshot(
    state: dict[str, Any] | str,
    label: str,
    parent_snapshot: dict[str, Any] | str | None = None,
    metadata: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Create a content-addressed project state snapshot suitable for diff and rollback."""
    state_obj = _mapping(state, "version_state")
    parent = _mapping(parent_snapshot, "parent_snapshot") if parent_snapshot else None
    if parent and parent.get("type") != "version_snapshot":
        raise ContinuityValidationError("parent_snapshot 类型错误")
    item_fingerprints: dict[str, str] = {}
    for key, value in sorted(state_obj.items()):
        item_fingerprints[str(key)] = _sha(value)
    parent_id = parent.get("snapshot_id") if parent else None
    snapshot_id = f"snap-{_sha([label, parent_id, item_fingerprints], 16)}"
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "version_snapshot",
        "snapshot_id": snapshot_id,
        "label": str(label).strip() or snapshot_id,
        "parent_snapshot_id": parent_id,
        "parent_fingerprint": parent.get("fingerprint") if parent else None,
        "state": state_obj,
        "item_fingerprints": item_fingerprints,
        "metadata": _mapping(metadata, "metadata") if metadata else {},
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def verify_version_snapshot(snapshot: dict[str, Any] | str) -> dict[str, Any]:
    obj = _mapping(snapshot, "version_snapshot")
    issues: list[dict[str, Any]] = []
    if obj.get("type") != "version_snapshot":
        issues.append(make_issue("SNAPSHOT_TYPE_INVALID", "error", "type", "版本快照类型错误"))
    state = obj.get("state")
    expected = obj.get("item_fingerprints")
    if not isinstance(state, dict) or not isinstance(expected, dict):
        issues.append(make_issue("SNAPSHOT_STATE_INVALID", "error", "state", "版本快照缺少状态或指纹表"))
    else:
        for key, value in state.items():
            actual = _sha(value)
            if expected.get(str(key)) != actual:
                issues.append(make_issue("SNAPSHOT_ITEM_TAMPERED", "error", f"state.{key}", "快照项目指纹不一致", expected=expected.get(str(key)), actual=actual))
        for key in expected:
            if key not in state:
                issues.append(make_issue("SNAPSHOT_ITEM_MISSING", "error", f"state.{key}", "快照项目缺失"))
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "version_snapshot_verification",
        "snapshot_id": obj.get("snapshot_id"),
        "valid": not any(issue.get("severity") == "error" for issue in issues),
        "issues": issues,
        "checked_items": len(state) if isinstance(state, dict) else 0,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result

CRITICAL_DIFF_PATTERNS = (
    re.compile(r"(?:^|\.)(?:project_id|character_id|scene_id|master_seed|seed)$"),
    re.compile(r"(?:^|\.)(?:identity_anchor|default_wardrobe|signature_props|reference_images)$"),
    re.compile(r"(?:^|\.)(?:fps|aspect_ratio|model_profile|workflow_template)$"),
)


def build_structured_diff(
    before: dict[str, Any] | str,
    after: dict[str, Any] | str,
    ignore_paths: list[str] | str | None = None,
    max_changes: int = 5000,
) -> dict[str, Any]:
    """Produce a deterministic recursive diff for snapshots or arbitrary JSON objects."""
    left = _mapping(before, "before")
    right = _mapping(after, "after")
    if left.get("type") == "version_snapshot":
        left = _mapping(left.get("state", {}), "before.state")
    if right.get("type") == "version_snapshot":
        right = _mapping(right.get("state", {}), "after.state")
    ignored = set(str(item).strip() for item in _list(ignore_paths, "ignore_paths") if str(item).strip()) if ignore_paths else set()
    changes: list[dict[str, Any]] = []
    truncated = False

    def ignored_path(path: str) -> bool:
        return any(path == item or path.startswith(f"{item}.") for item in ignored)

    def walk(a: Any, b: Any, path: str) -> None:
        nonlocal truncated
        if truncated or ignored_path(path):
            return
        if len(changes) >= max(1, int(max_changes)):
            truncated = True
            return
        if type(a) is not type(b):
            changes.append({"path": path or "$", "change": "type_changed", "before": deepcopy(a), "after": deepcopy(b)})
            return
        if isinstance(a, dict):
            for key in sorted(set(a) | set(b), key=str):
                child = f"{path}.{key}" if path else str(key)
                if key not in a:
                    changes.append({"path": child, "change": "added", "after": deepcopy(b[key])})
                elif key not in b:
                    changes.append({"path": child, "change": "removed", "before": deepcopy(a[key])})
                else:
                    walk(a[key], b[key], child)
                if len(changes) >= max(1, int(max_changes)):
                    truncated = True
                    return
            return
        if isinstance(a, list):
            common = min(len(a), len(b))
            for index in range(common):
                walk(a[index], b[index], f"{path}[{index}]")
                if truncated:
                    return
            for index in range(common, len(a)):
                changes.append({"path": f"{path}[{index}]", "change": "removed", "before": deepcopy(a[index])})
            for index in range(common, len(b)):
                changes.append({"path": f"{path}[{index}]", "change": "added", "after": deepcopy(b[index])})
            return
        if a != b:
            changes.append({"path": path or "$", "change": "changed", "before": deepcopy(a), "after": deepcopy(b)})

    walk(left, right, "")
    counts = {"added": 0, "removed": 0, "changed": 0, "type_changed": 0}
    critical = []
    for change in changes:
        counts[change["change"]] = counts.get(change["change"], 0) + 1
        normalized_path = re.sub(r"\[\d+\]", "", change["path"])
        if any(pattern.search(normalized_path) for pattern in CRITICAL_DIFF_PATTERNS):
            critical.append(change)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "structured_diff",
        "before_fingerprint": _sha(left),
        "after_fingerprint": _sha(right),
        "changes": changes,
        "change_count": len(changes),
        "counts": counts,
        "critical_changes": critical,
        "critical_change_count": len(critical),
        "ignored_paths": sorted(ignored),
        "truncated": truncated,
        "identical": not changes and not truncated,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result

PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_MISSING = object()


def _path_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for name, index in PATH_TOKEN_RE.findall(str(path)):
        tokens.append(int(index) if index else name)
    if not tokens:
        raise ContinuityValidationError(f"无效路径：{path}")
    return tokens


def _get_path(data: Any, path: str, default: Any = _MISSING) -> Any:
    current = data
    for token in _path_tokens(path):
        try:
            current = current[token]
        except (KeyError, IndexError, TypeError):
            if default is not _MISSING:
                return default
            raise ContinuityValidationError(f"路径不存在：{path}")
    return current


def _set_path(data: Any, path: str, value: Any) -> None:
    tokens = _path_tokens(path)
    current = data
    for token in tokens[:-1]:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise ContinuityValidationError(f"无法设置路径：{path}")
            current = current[token]
        else:
            if not isinstance(current, dict):
                raise ContinuityValidationError(f"无法设置路径：{path}")
            if token not in current or not isinstance(current[token], (dict, list)):
                current[token] = {}
            current = current[token]
    final = tokens[-1]
    if isinstance(final, int):
        if not isinstance(current, list) or final >= len(current):
            raise ContinuityValidationError(f"无法设置路径：{path}")
        current[final] = deepcopy(value)
    else:
        if not isinstance(current, dict):
            raise ContinuityValidationError(f"无法设置路径：{path}")
        current[final] = deepcopy(value)


def _delete_path(data: Any, path: str) -> None:
    tokens = _path_tokens(path)
    current = data
    for token in tokens[:-1]:
        try:
            current = current[token]
        except (KeyError, IndexError, TypeError):
            return
    final = tokens[-1]
    if isinstance(final, int) and isinstance(current, list) and final < len(current):
        current.pop(final)
    elif isinstance(final, str) and isinstance(current, dict):
        current.pop(final, None)


def build_rollback_plan(
    current_snapshot: dict[str, Any] | str,
    target_snapshot: dict[str, Any] | str,
    scope_paths: list[str] | str | None = None,
) -> dict[str, Any]:
    current = _mapping(current_snapshot, "current_snapshot")
    target = _mapping(target_snapshot, "target_snapshot")
    if current.get("type") != "version_snapshot" or target.get("type") != "version_snapshot":
        raise ContinuityValidationError("回滚需要两个 version_snapshot")
    verification = verify_version_snapshot(target)
    if not verification["valid"]:
        raise ContinuityValidationError("目标版本快照校验失败")
    current_state = _mapping(current.get("state", {}), "current.state")
    target_state = _mapping(target.get("state", {}), "target.state")
    scopes = [str(item).strip() for item in _list(scope_paths, "scope_paths") if str(item).strip()] if scope_paths else []
    operations: list[dict[str, Any]] = []
    if not scopes:
        operations.append({"operation": "replace_root", "path": "$", "value": deepcopy(target_state)})
    else:
        for path in sorted(set(scopes)):
            target_value = _get_path(target_state, path, _MISSING)
            current_value = _get_path(current_state, path, _MISSING)
            if target_value is _MISSING:
                if current_value is not _MISSING:
                    operations.append({"operation": "delete", "path": path})
            elif current_value is _MISSING or current_value != target_value:
                operations.append({"operation": "set", "path": path, "value": deepcopy(target_value)})
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "rollback_plan",
        "current_snapshot_id": current.get("snapshot_id"),
        "target_snapshot_id": target.get("snapshot_id"),
        "current_state_fingerprint": _sha(current_state),
        "target_state_fingerprint": _sha(target_state),
        "scope_paths": scopes,
        "operations": operations,
        "operation_count": len(operations),
        "no_op": not operations,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def apply_rollback_plan(
    current_state: dict[str, Any] | str,
    rollback_plan: dict[str, Any] | str,
    require_fingerprint_match: bool = True,
) -> dict[str, Any]:
    state = _mapping(current_state, "current_state")
    plan = _mapping(rollback_plan, "rollback_plan")
    if plan.get("type") != "rollback_plan":
        raise ContinuityValidationError("rollback_plan 类型错误")
    if require_fingerprint_match and _sha(state) != plan.get("current_state_fingerprint"):
        raise ContinuityValidationError("当前状态已变化，拒绝应用过期回滚计划")
    result_state = deepcopy(state)
    for operation in plan.get("operations", []):
        kind = operation.get("operation")
        path = operation.get("path")
        if kind == "replace_root":
            result_state = _mapping(operation.get("value", {}), "rollback root")
        elif kind == "set":
            _set_path(result_state, str(path), operation.get("value"))
        elif kind == "delete":
            _delete_path(result_state, str(path))
        else:
            raise ContinuityValidationError(f"未知回滚操作：{kind}")
    actual = _sha(result_state)
    if not plan.get("scope_paths") and actual != plan.get("target_state_fingerprint"):
        raise ContinuityValidationError("完整回滚结果与目标快照不一致")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "rollback_result",
        "target_snapshot_id": plan.get("target_snapshot_id"),
        "state": result_state,
        "state_fingerprint": actual,
        "applied_operations": len(plan.get("operations", [])),
        "success": True,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def plan_batch_rerun(
    queue_state: dict[str, Any] | str,
    quality_evaluations: list[dict[str, Any]] | str | None = None,
    boundary_reports: list[dict[str, Any]] | str | None = None,
    selected_shot_ids: list[str] | str | None = None,
    max_tasks: int = 100,
    priority_boost: int = 10,
) -> dict[str, Any]:
    """Create deterministic rerun tasks only for failed or explicitly selected shots."""
    state = _mapping(queue_state, "queue_state")
    if state.get("type") != "persistent_queue":
        raise ContinuityValidationError("queue_state 类型错误")
    targets: dict[str, set[str]] = {}
    for item in _list(quality_evaluations, "quality_evaluations") if quality_evaluations else []:
        if not isinstance(item, dict):
            continue
        if item.get("decision") == "fail" or not bool(item.get("passed", item.get("decision") == "pass")):
            shot_id = str(item.get("shot_id", "")).strip()
            if shot_id:
                targets.setdefault(shot_id, set()).add("quality_failed")
    for item in _list(boundary_reports, "boundary_reports") if boundary_reports else []:
        if not isinstance(item, dict) or bool(item.get("passed", False)):
            continue
        for key in ("previous_shot_id", "next_shot_id"):
            shot_id = str(item.get(key, "")).strip()
            if shot_id:
                targets.setdefault(shot_id, set()).add("boundary_failed")
    for shot_id in _list(selected_shot_ids, "selected_shot_ids") if selected_shot_ids else []:
        cleaned = str(shot_id).strip()
        if cleaned:
            targets.setdefault(cleaned, set()).add("manually_selected")
    by_shot: dict[str, list[dict[str, Any]]] = {}
    for task in state.get("tasks", []):
        if isinstance(task, dict) and task.get("shot_id"):
            by_shot.setdefault(str(task["shot_id"]), []).append(task)
    requests: list[dict[str, Any]] = []
    missing: list[str] = []
    limit = max(1, min(int(max_tasks), 10000))
    for shot_id in sorted(targets):
        source_candidates = by_shot.get(shot_id, [])
        if not source_candidates:
            missing.append(shot_id)
            continue
        source_candidates.sort(key=lambda item: (
            0 if item.get("status") == "succeeded" else 1,
            -int(item.get("attempt", 1)),
            str(item.get("task_id", "")),
        ))
        source = source_candidates[0]
        rerun_index = 1 + sum(1 for task in source_candidates if str(task.get("task_id", "")).startswith("rerun-"))
        base_seed = int(source.get("seed", 0) or 0)
        seed = int(_sha([base_seed, shot_id, rerun_index, sorted(targets[shot_id])], 16), 16) & (2**63 - 1)
        task_id = f"rerun-{slugify(shot_id, 'shot')}-{rerun_index:02d}-{_sha([source.get('task_id'), seed], 8)}"
        requests.append({
            "task_id": task_id,
            "shot_id": shot_id,
            "take_index": int(source.get("take_index", 1)),
            "status": "queued",
            "attempt": 1,
            "priority": int(source.get("priority", 0)) + int(priority_boost),
            "requires_tasks": deepcopy(source.get("requires_tasks", [])),
            "provider": source.get("provider"),
            "seed": seed,
            "source_task_id": source.get("task_id"),
            "rerun_index": rerun_index,
            "rerun_reasons": sorted(targets[shot_id]),
            "payload": deepcopy(source.get("payload", {})),
        })
        if len(requests) >= limit:
            break
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "batch_rerun_plan",
        "queue_id": state.get("queue_id"),
        "queue_revision": state.get("revision"),
        "queue_fingerprint": state.get("fingerprint"),
        "requests": requests,
        "request_count": len(requests),
        "target_shot_ids": sorted(targets),
        "missing_shot_ids": missing,
        "truncated": len(requests) >= limit and len(targets) > len(requests),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def apply_batch_rerun_plan(
    queue_state: dict[str, Any] | str,
    rerun_plan: dict[str, Any] | str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    state = _mapping(queue_state, "queue_state")
    plan = _mapping(rerun_plan, "batch_rerun_plan")
    if state.get("type") != "persistent_queue" or plan.get("type") != "batch_rerun_plan":
        raise ContinuityValidationError("queue_state 或 batch_rerun_plan 类型错误")
    if plan.get("queue_id") != state.get("queue_id"):
        raise ContinuityValidationError("重跑计划不属于当前队列")
    if int(plan.get("queue_revision", -1)) != int(state.get("revision", 0)) or plan.get("queue_fingerprint") != state.get("fingerprint"):
        raise ContinuityValidationError("队列已变化，拒绝应用过期重跑计划")
    existing = {str(task.get("task_id")) for task in state.get("tasks", []) if isinstance(task, dict)}
    timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
    added = []
    for raw in plan.get("requests", []):
        task = deepcopy(raw)
        task_id = str(task.get("task_id", ""))
        if not task_id or task_id in existing:
            continue
        task["created_at_ms"] = timestamp
        task["updated_at_ms"] = timestamp
        task["history"] = []
        task["fingerprint"] = _sha({key: value for key, value in task.items() if key != "fingerprint"}, 32)
        state.setdefault("tasks", []).append(task)
        existing.add(task_id)
        added.append(task_id)
    if added:
        state["task_count"] = len(state.get("tasks", []))
        state["revision"] = int(state.get("revision", 0)) + 1
        state["updated_at_ms"] = timestamp
        state["fingerprint"] = manifest_fingerprint(state)
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "batch_rerun_result",
        "queue_state": state,
        "added_task_ids": added,
        "added_count": len(added),
        "plan_fingerprint": plan.get("fingerprint"),
    }

RESOURCE_FIELDS = (
    "tasks",
    "concurrent_tasks",
    "gpu_seconds",
    "estimated_cost",
    "storage_bytes",
    "remakes",
)


def build_resource_quota(spec: dict[str, Any] | str) -> dict[str, Any]:
    obj = _mapping(spec, "resource_quota")
    limits_raw = obj.get("limits", obj)
    if not isinstance(limits_raw, dict):
        raise ContinuityValidationError("resource_quota.limits 必须是对象")
    limits: dict[str, float | int | None] = {}
    integer_fields = {"tasks", "concurrent_tasks", "storage_bytes", "remakes"}
    for field in RESOURCE_FIELDS:
        value = limits_raw.get(field)
        if value in (None, ""):
            limits[field] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ContinuityValidationError(f"limits.{field} 必须是数字或 null") from exc
        if number < 0:
            raise ContinuityValidationError(f"limits.{field} 不能为负数")
        limits[field] = int(number) if field in integer_fields else round(number, 6)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "resource_quota",
        "quota_id": slugify(obj.get("quota_id") or obj.get("name"), "quota"),
        "limits": limits,
        "used": {field: 0 for field in RESOURCE_FIELDS},
        "reservations": [],
        "revision": 1,
        "metadata": deepcopy(obj.get("metadata", {})) if isinstance(obj.get("metadata", {}), dict) else {},
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def evaluate_resource_quota(
    resource_quota: dict[str, Any] | str,
    requested: dict[str, Any] | str,
) -> dict[str, Any]:
    quota = _mapping(resource_quota, "resource_quota")
    if quota.get("type") != "resource_quota":
        raise ContinuityValidationError("resource_quota 类型错误")
    request = _mapping(requested, "requested_resources")
    exceeded: list[dict[str, Any]] = []
    remaining: dict[str, float | int | None] = {}
    normalized_request: dict[str, float | int] = {}
    for field in RESOURCE_FIELDS:
        value = request.get(field, 0)
        try:
            amount = float(value or 0)
        except (TypeError, ValueError) as exc:
            raise ContinuityValidationError(f"requested.{field} 必须是数字") from exc
        if amount < 0:
            raise ContinuityValidationError(f"requested.{field} 不能为负数")
        if field in {"tasks", "concurrent_tasks", "storage_bytes", "remakes"}:
            normalized_request[field] = int(amount)
        else:
            normalized_request[field] = round(amount, 6)
        limit = quota.get("limits", {}).get(field)
        used = float(quota.get("used", {}).get(field, 0) or 0)
        if limit is None:
            remaining[field] = None
            continue
        left = float(limit) - used
        remaining[field] = int(max(0, left)) if field in {"tasks", "concurrent_tasks", "storage_bytes", "remakes"} else round(max(0.0, left), 6)
        if amount > left + 1e-9:
            exceeded.append({"resource": field, "limit": limit, "used": used, "requested": amount, "remaining": max(0.0, left)})
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "resource_quota_evaluation",
        "quota_id": quota.get("quota_id"),
        "quota_revision": quota.get("revision"),
        "quota_fingerprint": quota.get("fingerprint"),
        "requested": normalized_request,
        "remaining_before": remaining,
        "allowed": not exceeded,
        "exceeded": exceeded,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def reserve_resource_quota(
    resource_quota: dict[str, Any] | str,
    evaluation: dict[str, Any] | str,
    reservation_id: str,
    metadata: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    quota = _mapping(resource_quota, "resource_quota")
    report = _mapping(evaluation, "resource_quota_evaluation")
    if quota.get("type") != "resource_quota" or report.get("type") != "resource_quota_evaluation":
        raise ContinuityValidationError("resource_quota 或 evaluation 类型错误")
    if report.get("quota_id") != quota.get("quota_id") or report.get("quota_fingerprint") != quota.get("fingerprint"):
        raise ContinuityValidationError("资源配额已变化，拒绝应用过期评估")
    if not report.get("allowed"):
        raise ContinuityValidationError("资源请求超过配额")
    rid = slugify(reservation_id, "reservation")
    if any(item.get("reservation_id") == rid for item in quota.get("reservations", []) if isinstance(item, dict)):
        raise ContinuityValidationError(f"资源预留 ID 重复：{rid}")
    request = report.get("requested", {})
    for field in RESOURCE_FIELDS:
        quota.setdefault("used", {})[field] = quota.setdefault("used", {}).get(field, 0) + request.get(field, 0)
    quota.setdefault("reservations", []).append({
        "reservation_id": rid,
        "resources": deepcopy(request),
        "metadata": _mapping(metadata, "metadata") if metadata else {},
    })
    quota["revision"] = int(quota.get("revision", 0)) + 1
    quota["fingerprint"] = manifest_fingerprint(quota)
    return quota

METRIC_NAME_RE = re.compile(r"[^a-zA-Z0-9_:]")


def _metric_name(value: str) -> str:
    cleaned = METRIC_NAME_RE.sub("_", value)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"metric_{cleaned}"
    return cleaned


def collect_observability_metrics(
    queue_state: dict[str, Any] | str | None = None,
    trace_summary: dict[str, Any] | str | None = None,
    asset_index: dict[str, Any] | str | None = None,
    qc_reports: list[dict[str, Any]] | str | None = None,
    namespace: str = "continuity_director",
) -> dict[str, Any]:
    """Collect portable counters/gauges and render Prometheus text without network access."""
    prefix = _metric_name(slugify(namespace, "continuity_director").replace("-", "_"))
    samples: list[dict[str, Any]] = []

    def add(name: str, value: float | int, kind: str = "gauge", labels: dict[str, str] | None = None, help_text: str = "") -> None:
        samples.append({
            "name": _metric_name(f"{prefix}_{name}"),
            "value": float(value),
            "kind": kind,
            "labels": dict(sorted((labels or {}).items())),
            "help": help_text,
        })

    if queue_state:
        queue = _mapping(queue_state, "queue_state")
        counts: dict[str, int] = {}
        for task in queue.get("tasks", []):
            if isinstance(task, dict):
                status = str(task.get("status", "unknown"))
                counts[status] = counts.get(status, 0) + 1
        add("queue_tasks_total", len(queue.get("tasks", [])), "gauge", help_text="Tasks in persistent queue")
        add("queue_revision", int(queue.get("revision", 0)), "gauge", help_text="Persistent queue revision")
        for status, count in sorted(counts.items()):
            add("queue_tasks", count, "gauge", {"status": status}, "Tasks by state")
    if trace_summary:
        trace = _mapping(trace_summary, "trace_summary")
        add("trace_events_total", int(trace.get("event_count", 0)), "counter", help_text="Trace events")
        add("run_duration_milliseconds", int(trace.get("duration_ms", 0)), "gauge", help_text="Run duration in milliseconds")
        for level, count in sorted((trace.get("events_by_level") or {}).items()):
            add("trace_events", int(count), "counter", {"level": str(level)}, "Trace events by level")
    if asset_index:
        assets = _mapping(asset_index, "asset_index")
        add("assets_total", int(assets.get("asset_count", len(assets.get("assets", [])))), "gauge", help_text="Indexed assets")
        add("asset_duplicates_total", int(assets.get("duplicate_count", 0)), "gauge", help_text="Duplicate assets")
        total_bytes = sum(int(item.get("size_bytes", 0) or 0) for item in assets.get("assets", []) if isinstance(item, dict))
        add("asset_storage_bytes", total_bytes, "gauge", help_text="Indexed asset bytes")
    reports = _list(qc_reports, "qc_reports") if qc_reports else []
    if reports:
        decisions: dict[str, int] = {}
        scores = []
        for report in reports:
            if not isinstance(report, dict):
                continue
            decision = str(report.get("decision", "unknown"))
            decisions[decision] = decisions.get(decision, 0) + 1
            if isinstance(report.get("score"), (int, float)):
                scores.append(float(report["score"]))
            elif isinstance(report.get("overall_score"), (int, float)):
                scores.append(float(report["overall_score"]))
        add("qc_reports_total", len(reports), "gauge", help_text="Quality reports")
        for decision, count in sorted(decisions.items()):
            add("qc_reports", count, "gauge", {"decision": decision}, "Quality reports by decision")
        if scores:
            add("qc_score_average", sum(scores) / len(scores), "gauge", help_text="Average quality score")
    lines: list[str] = []
    described: set[str] = set()
    for sample in samples:
        name = sample["name"]
        if name not in described:
            if sample.get("help"):
                lines.append(f"# HELP {name} {sample['help']}")
            lines.append(f"# TYPE {name} {sample['kind']}")
            described.add(name)
        labels = sample.get("labels") or {}
        label_text = ""
        if labels:
            encoded = []
            for key, value in labels.items():
                safe_value = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                encoded.append(f'{_metric_name(key)}="{safe_value}"')
            label_text = "{" + ",".join(encoded) + "}"
        value = sample["value"]
        rendered = str(int(value)) if float(value).is_integer() else f"{value:.6f}".rstrip("0").rstrip(".")
        lines.append(f"{name}{label_text} {rendered}")
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "observability_metrics",
        "namespace": prefix,
        "samples": samples,
        "sample_count": len(samples),
        "prometheus_text": "\n".join(lines) + ("\n" if lines else ""),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def build_system_health_report(
    queue_state: dict[str, Any] | str | None = None,
    trace_summary: dict[str, Any] | str | None = None,
    resource_quota: dict[str, Any] | str | None = None,
    quality_reports: list[dict[str, Any]] | str | None = None,
    now_ms: int | None = None,
    stalled_task_seconds: int = 900,
) -> dict[str, Any]:
    """Summarize scheduler, quality, trace and quota health into actionable checks."""
    timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
    checks: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if queue_state:
        queue = _mapping(queue_state, "queue_state")
        if queue.get("type") != "persistent_queue":
            raise ContinuityValidationError("queue_state 类型错误")
        tasks = [task for task in queue.get("tasks", []) if isinstance(task, dict)]
        expired = []
        stalled = []
        for task in tasks:
            lease = task.get("lease")
            if isinstance(lease, dict) and task.get("status") in {"leased", "running"} and int(lease.get("expires_at_ms", 0)) <= timestamp:
                expired.append(task.get("task_id"))
            if task.get("status") in {"leased", "running"}:
                age = timestamp - int(task.get("updated_at_ms", timestamp))
                if age > max(1, int(stalled_task_seconds)) * 1000:
                    stalled.append(task.get("task_id"))
        failed = [task.get("task_id") for task in tasks if task.get("status") == "failed"]
        blocked = [task.get("task_id") for task in tasks if task.get("status") == "blocked"]
        checks.append({"check": "queue_expired_leases", "status": "fail" if expired else "pass", "count": len(expired), "task_ids": expired})
        checks.append({"check": "queue_stalled_tasks", "status": "warning" if stalled else "pass", "count": len(stalled), "task_ids": stalled})
        checks.append({"check": "queue_failed_tasks", "status": "warning" if failed else "pass", "count": len(failed), "task_ids": failed})
        checks.append({"check": "queue_blocked_tasks", "status": "warning" if blocked else "pass", "count": len(blocked), "task_ids": blocked})
        if expired:
            recommendations.append("运行租约回收节点，将过期任务重新排队或标记失败")
        if stalled:
            recommendations.append("检查工作进程、显存占用和模型日志，并续租或回收停滞任务")
    if trace_summary:
        trace = _mapping(trace_summary, "trace_summary")
        errors = int((trace.get("events_by_level") or {}).get("error", 0))
        warnings = int((trace.get("events_by_level") or {}).get("warning", 0))
        checks.append({"check": "trace_errors", "status": "fail" if errors else "pass", "count": errors})
        checks.append({"check": "trace_warnings", "status": "warning" if warnings else "pass", "count": warnings})
        if errors:
            recommendations.append("查看追踪日志中的 error 事件并按任务 ID 定位失败阶段")
    if resource_quota:
        quota = _mapping(resource_quota, "resource_quota")
        pressure = []
        for field, limit in (quota.get("limits") or {}).items():
            if limit in (None, 0):
                continue
            used = float((quota.get("used") or {}).get(field, 0) or 0)
            ratio = used / float(limit)
            if ratio >= 0.9:
                pressure.append({"resource": field, "used": used, "limit": limit, "ratio": round(ratio, 4)})
        checks.append({"check": "resource_pressure", "status": "warning" if pressure else "pass", "resources": pressure})
        if pressure:
            recommendations.append("资源配额已接近上限，暂停新增任务或释放不再需要的预留")
    reports = _list(quality_reports, "quality_reports") if quality_reports else []
    if reports:
        failed_reports = [item for item in reports if isinstance(item, dict) and item.get("decision") == "fail"]
        checks.append({"check": "quality_failures", "status": "warning" if failed_reports else "pass", "count": len(failed_reports)})
        if failed_reports:
            recommendations.append("对失败镜头生成定向重做计划，不要重新生成已通过镜头")
    rank = {"pass": 0, "warning": 1, "fail": 2}
    worst = max((rank.get(str(check.get("status")), 0) for check in checks), default=0)
    status = "healthy" if worst == 0 else ("degraded" if worst == 1 else "unhealthy")
    score = 100
    for check in checks:
        score -= 20 if check.get("status") == "fail" else (8 if check.get("status") == "warning" else 0)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "system_health_report",
        "timestamp_ms": timestamp,
        "status": status,
        "score": max(0, score),
        "checks": checks,
        "recommendations": list(dict.fromkeys(recommendations)),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def create_regression_baseline(
    results: list[dict[str, Any]] | str,
    suite_id: str,
    metadata: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    items = _list(results, "regression_results")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"regression_results[{index}] 必须是对象")
        case_id = slugify(raw.get("case_id") or raw.get("name"), f"case-{index + 1}")
        if case_id in seen:
            raise ContinuityValidationError(f"回归用例 ID 重复：{case_id}")
        seen.add(case_id)
        output = deepcopy(raw.get("output"))
        metrics = deepcopy(raw.get("metrics", {})) if isinstance(raw.get("metrics", {}), dict) else {}
        cases.append({
            "case_id": case_id,
            "output_fingerprint": _sha(output),
            "metrics": metrics,
            "metadata": deepcopy(raw.get("metadata", {})) if isinstance(raw.get("metadata", {}), dict) else {},
        })
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "regression_baseline",
        "suite_id": slugify(suite_id, "regression-suite"),
        "cases": cases,
        "case_count": len(cases),
        "metadata": _mapping(metadata, "metadata") if metadata else {},
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def compare_regression_results(
    baseline: dict[str, Any] | str,
    current_results: list[dict[str, Any]] | str,
    metric_tolerances: dict[str, Any] | str | None = None,
    allow_output_change: bool = False,
) -> dict[str, Any]:
    base = _mapping(baseline, "regression_baseline")
    if base.get("type") != "regression_baseline":
        raise ContinuityValidationError("regression_baseline 类型错误")
    tolerances = _mapping(metric_tolerances, "metric_tolerances") if metric_tolerances else {}
    current = _list(current_results, "current_results")
    current_map: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(current):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"current_results[{index}] 必须是对象")
        case_id = slugify(raw.get("case_id") or raw.get("name"), f"case-{index + 1}")
        if case_id in current_map:
            raise ContinuityValidationError(f"当前回归用例 ID 重复：{case_id}")
        current_map[case_id] = raw
    reports: list[dict[str, Any]] = []
    failures = 0
    baseline_ids = {case.get("case_id") for case in base.get("cases", []) if isinstance(case, dict)}
    for case in base.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id"))
        actual = current_map.get(case_id)
        issues: list[dict[str, Any]] = []
        if actual is None:
            issues.append(make_issue("REGRESSION_CASE_MISSING", "error", case_id, "当前结果缺少回归用例"))
        else:
            actual_fingerprint = _sha(actual.get("output"))
            if actual_fingerprint != case.get("output_fingerprint") and not allow_output_change:
                issues.append(make_issue("REGRESSION_OUTPUT_CHANGED", "error", case_id, "用例输出指纹发生变化", expected=case.get("output_fingerprint"), actual=actual_fingerprint))
            actual_metrics = actual.get("metrics", {}) if isinstance(actual.get("metrics", {}), dict) else {}
            for metric_name, expected_value in (case.get("metrics") or {}).items():
                if metric_name not in actual_metrics:
                    issues.append(make_issue("REGRESSION_METRIC_MISSING", "error", f"{case_id}.{metric_name}", "当前结果缺少指标"))
                    continue
                if not isinstance(expected_value, (int, float)) or not isinstance(actual_metrics[metric_name], (int, float)):
                    if actual_metrics[metric_name] != expected_value:
                        issues.append(make_issue("REGRESSION_METRIC_CHANGED", "error", f"{case_id}.{metric_name}", "非数值指标发生变化", expected=expected_value, actual=actual_metrics[metric_name]))
                    continue
                tolerance = float(tolerances.get(metric_name, 0))
                delta = float(actual_metrics[metric_name]) - float(expected_value)
                if abs(delta) > tolerance:
                    issues.append(make_issue("REGRESSION_METRIC_DRIFT", "error", f"{case_id}.{metric_name}", "指标偏移超过容差", expected=expected_value, actual=actual_metrics[metric_name], delta=round(delta, 6), tolerance=tolerance))
        passed = not any(issue.get("severity") == "error" for issue in issues)
        failures += 0 if passed else 1
        reports.append({"case_id": case_id, "passed": passed, "issues": issues})
    unexpected = sorted(set(current_map) - baseline_ids)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "regression_comparison",
        "suite_id": base.get("suite_id"),
        "baseline_fingerprint": base.get("fingerprint"),
        "reports": reports,
        "case_count": len(reports),
        "failure_count": failures,
        "unexpected_case_ids": unexpected,
        "passed": failures == 0,
        "allow_output_change": bool(allow_output_change),
        "metric_tolerances": tolerances,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result

CONFIG_SECRET_RE = re.compile(r"(?:api[_-]?key|token|secret|password|authorization|cookie)", re.IGNORECASE)


def _scrub_secrets(value: Any, path: str = "config", redacted: list[str] | None = None) -> Any:
    targets = redacted if redacted is not None else []
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            child = f"{path}.{key}"
            if CONFIG_SECRET_RE.search(str(key)):
                result[key] = "[REDACTED]"
                targets.append(child)
            else:
                result[key] = _scrub_secrets(item, child, targets)
        return result
    if isinstance(value, list):
        return [_scrub_secrets(item, f"{path}[{index}]", targets) for index, item in enumerate(value)]
    return deepcopy(value)


def package_configuration_bundle(
    path: str | os.PathLike[str],
    configurations: dict[str, Any] | str,
    overwrite: bool = False,
) -> Path:
    """Export declarative plugin configurations to a secret-free, checksummed ZIP."""
    configs = _mapping(configurations, "configurations")
    if not configs:
        raise ContinuityValidationError("configurations 不能为空")
    files: dict[str, bytes] = {}
    redacted_paths: list[str] = []
    entries = []
    for name, value in sorted(configs.items()):
        safe_name = slugify(str(name), "config")
        scrubbed = _scrub_secrets(value, f"configurations.{name}", redacted_paths)
        filename = f"configs/{safe_name}.json"
        content = json.dumps(scrubbed, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        files[filename] = content
        entries.append({"name": str(name), "file": filename, "sha256": hashlib.sha256(content).hexdigest(), "type": scrubbed.get("type") if isinstance(scrubbed, dict) else None})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "type": "configuration_bundle",
        "entries": entries,
        "entry_count": len(entries),
        "redacted_paths": sorted(set(redacted_paths)),
    }
    manifest["fingerprint"] = manifest_fingerprint(manifest)
    files["bundle_manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        counter = 2
        original = target
        while target.exists():
            target = original.with_name(f"{original.stem}-{counter}{original.suffix}")
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


def load_configuration_bundle(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    issues: list[dict[str, Any]] = []
    configurations: dict[str, Any] = {}
    if not source.is_file():
        return {"schema_version": SCHEMA_VERSION, "type": "configuration_bundle_load", "valid": False, "configurations": {}, "issues": [make_issue("CONFIG_BUNDLE_NOT_FOUND", "error", "path", "配置包不存在")]}
    try:
        with zipfile.ZipFile(source, "r") as archive:
            names = archive.namelist()
            unsafe = [name for name in names if name.startswith(("/", "\\")) or ".." in Path(name).parts]
            if unsafe:
                issues.append(make_issue("CONFIG_BUNDLE_UNSAFE_PATH", "error", "archive", "配置包包含危险路径", paths=unsafe))
            if len(names) != len(set(names)):
                issues.append(make_issue("CONFIG_BUNDLE_DUPLICATE_ENTRY", "error", "archive", "配置包包含重复文件"))
            if "bundle_manifest.json" not in names:
                issues.append(make_issue("CONFIG_BUNDLE_MANIFEST_MISSING", "error", "bundle_manifest.json", "配置包缺少清单"))
            else:
                manifest = json.loads(archive.read("bundle_manifest.json").decode("utf-8"))
                for entry in manifest.get("entries", []):
                    if not isinstance(entry, dict):
                        continue
                    filename = str(entry.get("file", ""))
                    if filename not in names:
                        issues.append(make_issue("CONFIG_BUNDLE_FILE_MISSING", "error", filename, "配置文件缺失"))
                        continue
                    content = archive.read(filename)
                    actual = hashlib.sha256(content).hexdigest()
                    if actual != entry.get("sha256"):
                        issues.append(make_issue("CONFIG_BUNDLE_CHECKSUM_MISMATCH", "error", filename, "配置文件校验失败", expected=entry.get("sha256"), actual=actual))
                        continue
                    value = json.loads(content.decode("utf-8"))
                    configurations[str(entry.get("name") or Path(filename).stem)] = value
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        issues.append(make_issue("CONFIG_BUNDLE_CORRUPT", "error", "archive", "配置包损坏或内容无效", error=str(exc)))
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "configuration_bundle_load",
        "path": str(source),
        "valid": not any(issue.get("severity") == "error" for issue in issues),
        "configurations": configurations,
        "configuration_count": len(configurations),
        "issues": issues,
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def build_artifact_lineage(records: list[dict[str, Any]] | str) -> dict[str, Any]:
    """Build and validate a DAG describing how prompts, frames, videos and assemblies were derived."""
    items = _list(records, "lineage_records")
    nodes: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ContinuityValidationError(f"lineage_records[{index}] 必须是对象")
        artifact_id = slugify(raw.get("artifact_id") or raw.get("id"), f"artifact-{index + 1}")
        if artifact_id in nodes:
            raise ContinuityValidationError(f"artifact_id 重复：{artifact_id}")
        parents_raw = raw.get("parents", raw.get("parent_ids", []))
        if isinstance(parents_raw, str):
            parents_raw = [item.strip() for item in parents_raw.split(",") if item.strip()]
        if not isinstance(parents_raw, list):
            raise ContinuityValidationError(f"{artifact_id}.parents 必须是数组")
        parents = sorted(set(slugify(value, "") for value in parents_raw if slugify(value, "")))
        nodes[artifact_id] = {
            "artifact_id": artifact_id,
            "artifact_type": slugify(raw.get("artifact_type") or raw.get("type"), "artifact"),
            "source": str(raw.get("source", "")).strip() or None,
            "sha256": str(raw.get("sha256", "")).strip().lower() or None,
            "parents": parents,
            "metadata": deepcopy(raw.get("metadata", {})) if isinstance(raw.get("metadata", {}), dict) else {},
        }
    issues: list[dict[str, Any]] = []
    for artifact_id, node in nodes.items():
        unknown = [parent for parent in node["parents"] if parent not in nodes]
        if unknown:
            issues.append(make_issue("LINEAGE_PARENT_MISSING", "error", artifact_id, "产物引用了不存在的父节点", parents=unknown))
        if artifact_id in node["parents"]:
            issues.append(make_issue("LINEAGE_SELF_REFERENCE", "error", artifact_id, "产物不能引用自身"))
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[list[str]] = []

    def visit(node_id: str, stack: list[str]) -> None:
        if node_id in visiting:
            start = stack.index(node_id) if node_id in stack else 0
            cycle = stack[start:] + [node_id]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        stack.append(node_id)
        for parent in nodes.get(node_id, {}).get("parents", []):
            if parent in nodes:
                visit(parent, stack)
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(nodes):
        visit(node_id, [])
    for cycle in cycles:
        issues.append(make_issue("LINEAGE_CYCLE", "error", "graph", "产物血缘图存在循环", cycle=cycle))
    children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node_id, node in nodes.items():
        for parent in node["parents"]:
            if parent in children:
                children[parent].append(node_id)
    for node_id in children:
        children[node_id].sort()
    roots = sorted(node_id for node_id, node in nodes.items() if not node["parents"])
    leaves = sorted(node_id for node_id, values in children.items() if not values)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "artifact_lineage_graph",
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "children": children,
        "node_count": len(nodes),
        "edge_count": sum(len(node["parents"]) for node in nodes.values()),
        "root_ids": roots,
        "leaf_ids": leaves,
        "issues": issues,
        "valid": not any(issue.get("severity") == "error" for issue in issues),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result


def trace_artifact_lineage(lineage_graph: dict[str, Any] | str, artifact_id: str) -> dict[str, Any]:
    graph = _mapping(lineage_graph, "lineage_graph")
    if graph.get("type") != "artifact_lineage_graph":
        raise ContinuityValidationError("lineage_graph 类型错误")
    target = slugify(artifact_id, "artifact")
    by_id = {node.get("artifact_id"): node for node in graph.get("nodes", []) if isinstance(node, dict)}
    if target not in by_id:
        raise ContinuityValidationError(f"产物不存在：{target}")
    ancestors: set[str] = set()
    descendants: set[str] = set()

    def collect_parents(node_id: str) -> None:
        for parent in by_id.get(node_id, {}).get("parents", []):
            if parent not in ancestors:
                ancestors.add(parent)
                collect_parents(parent)

    def collect_children(node_id: str) -> None:
        for child in (graph.get("children") or {}).get(node_id, []):
            if child not in descendants:
                descendants.add(child)
                collect_children(child)

    collect_parents(target)
    collect_children(target)
    result = {
        "schema_version": SCHEMA_VERSION,
        "type": "artifact_lineage_trace",
        "artifact_id": target,
        "artifact": deepcopy(by_id[target]),
        "ancestor_ids": sorted(ancestors),
        "descendant_ids": sorted(descendants),
        "ancestor_count": len(ancestors),
        "descendant_count": len(descendants),
        "graph_fingerprint": graph.get("fingerprint"),
    }
    result["fingerprint"] = manifest_fingerprint(result)
    return result
