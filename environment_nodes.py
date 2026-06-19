"""Environment reproducibility node."""
from __future__ import annotations
from .continuity_core import stable_json
from .validation_core import environment_lock

RELIABILITY = "Continuity Director/07 Reliability"

class CDEnvironmentLock:
    RETURN_TYPES = ("CD_ENVIRONMENT_LOCK", "STRING", "STRING")
    RETURN_NAMES = ("environment_lock", "environment_json", "environment_hash")
    FUNCTION = "build"
    CATEGORY = RELIABILITY
    DESCRIPTION = "Record the runtime versions and model inventory required to reproduce a production run."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "comfyui_version": ("STRING", {"default": "unknown"}),
            "frontend_version": ("STRING", {"default": "unknown"}),
            "models_json": ("STRING", {"default": "[]", "multiline": True}),
            "notes": ("STRING", {"default": "", "multiline": True}),
        }}

    def build(self, comfyui_version, frontend_version, models_json, notes):
        result = environment_lock(comfyui_version, frontend_version, models_json, notes)
        return result, stable_json(result, indent=2), result["hash"]

NODE_CLASS_MAPPINGS = {"CDEnvironmentLock": CDEnvironmentLock}
NODE_DISPLAY_NAME_MAPPINGS = {"CDEnvironmentLock": "CD · Environment Lock"}
