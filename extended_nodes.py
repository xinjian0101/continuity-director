"""Reliability and package-governance nodes added after the initial v0.8 release."""

from __future__ import annotations

from .continuity_core import parse_json, stable_json
from .validation_core import migrate_payload, verify_hashed_payload

RELIABILITY = "Continuity Director/07 Reliability"


class CDVerifyPackage:
    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("valid", "verification_json", "expected_hash")
    FUNCTION = "verify"
    CATEGORY = RELIABILITY
    DESCRIPTION = "Verify the SHA-256 hash of a Continuity Director payload without executing its contents."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"payload_json": ("STRING", {"default": "{}", "multiline": True, "tooltip": "Hashed Continuity Director JSON payload."})}}

    def verify(self, payload_json):
        report = verify_hashed_payload(parse_json(payload_json, default={}, expected=dict))
        return report["valid"], stable_json(report, indent=2), report["expected_hash"]


class CDMigratePayload:
    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("migrated_json", "changes_json", "changed")
    FUNCTION = "migrate"
    CATEGORY = RELIABILITY
    DESCRIPTION = "Migrate a Continuity Director payload schema label and regenerate its integrity hash."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"payload_json": ("STRING", {"default": "{}", "multiline": True}), "target_version": ("STRING", {"default": "1.0"})}}

    def migrate(self, payload_json, target_version):
        migrated, changes = migrate_payload(payload_json, target_version)
        return stable_json(migrated, indent=2), stable_json(changes, indent=2), bool(changes)


NODE_CLASS_MAPPINGS = {"CDVerifyPackage": CDVerifyPackage, "CDMigratePayload": CDMigratePayload}
NODE_DISPLAY_NAME_MAPPINGS = {"CDVerifyPackage": "CD · Verify Package", "CDMigratePayload": "CD · Migrate Payload"}
