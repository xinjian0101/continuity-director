"""Reliability and package-governance nodes added after the initial v0.8 release."""

from __future__ import annotations

from .continuity_core import parse_json, stable_json
from .validation_core import verify_hashed_payload

RELIABILITY = "Continuity Director/07 Reliability"


class CDVerifyPackage:
    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("valid", "verification_json", "expected_hash")
    FUNCTION = "verify"
    CATEGORY = RELIABILITY
    DESCRIPTION = "Verify the SHA-256 hash of a Continuity Director payload without executing its contents."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "payload_json": (
                    "STRING",
                    {"default": "{}", "multiline": True, "tooltip": "Hashed Continuity Director JSON payload."},
                )
            }
        }

    def verify(self, payload_json):
        report = verify_hashed_payload(parse_json(payload_json, default={}, expected=dict))
        return report["valid"], stable_json(report, indent=2), report["expected_hash"]


NODE_CLASS_MAPPINGS = {"CDVerifyPackage": CDVerifyPackage}
NODE_DISPLAY_NAME_MAPPINGS = {"CDVerifyPackage": "CD · Verify Package"}
