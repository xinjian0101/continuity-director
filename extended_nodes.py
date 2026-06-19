"""Reliability and package-governance nodes added after the initial v0.8 release."""
from __future__ import annotations
from .continuity_core import parse_json, stable_json
from .validation_core import migrate_payload, queue_checkpoint, retry_policy, verify_hashed_payload

RELIABILITY = "Continuity Director/07 Reliability"

class CDVerifyPackage:
    RETURN_TYPES=("BOOLEAN","STRING","STRING"); RETURN_NAMES=("valid","verification_json","expected_hash"); FUNCTION="verify"; CATEGORY=RELIABILITY
    DESCRIPTION="Verify the SHA-256 hash of a Continuity Director payload without executing its contents."
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"payload_json":("STRING",{"default":"{}","multiline":True,"tooltip":"Hashed Continuity Director JSON payload."})}}
    def verify(self,payload_json):
        report=verify_hashed_payload(parse_json(payload_json,default={},expected=dict)); return report["valid"],stable_json(report,indent=2),report["expected_hash"]

class CDMigratePayload:
    RETURN_TYPES=("STRING","STRING","BOOLEAN"); RETURN_NAMES=("migrated_json","changes_json","changed"); FUNCTION="migrate"; CATEGORY=RELIABILITY
    DESCRIPTION="Migrate a Continuity Director payload schema label and regenerate its integrity hash."
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"payload_json":("STRING",{"default":"{}","multiline":True}),"target_version":("STRING",{"default":"1.0"})}}
    def migrate(self,payload_json,target_version):
        migrated,changes=migrate_payload(payload_json,target_version); return stable_json(migrated,indent=2),stable_json(changes,indent=2),bool(changes)

class CDRetryPolicy:
    RETURN_TYPES=("CD_RETRY_POLICY","STRING","FLOAT"); RETURN_NAMES=("retry_policy","retry_policy_json","first_delay_seconds"); FUNCTION="build"; CATEGORY=RELIABILITY
    DESCRIPTION="Create a deterministic bounded exponential retry schedule."
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"max_attempts":("INT",{"default":4,"min":1,"max":100}),"base_delay_seconds":("FLOAT",{"default":2.0,"min":0.0,"max":3600.0}),"multiplier":("FLOAT",{"default":2.0,"min":1.0,"max":10.0}),"max_delay_seconds":("FLOAT",{"default":60.0,"min":0.0,"max":86400.0})}}
    def build(self,max_attempts,base_delay_seconds,multiplier,max_delay_seconds):
        policy=retry_policy(max_attempts,base_delay_seconds,multiplier,max_delay_seconds); first=policy["delays_seconds"][0] if policy["delays_seconds"] else 0.0; return policy,stable_json(policy,indent=2),float(first)

class CDQueueCheckpoint:
    RETURN_TYPES=("CD_CHECKPOINT","STRING","INT"); RETURN_NAMES=("checkpoint","checkpoint_json","remaining_count"); FUNCTION="checkpoint"; CATEGORY=RELIABILITY
    DESCRIPTION="Create a resumable checkpoint from an execution plan and completed or failed task IDs."
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"execution_plan":("CD_EXECUTION_PLAN",),"completed_ids_json":("STRING",{"default":"[]","multiline":True}),"failed_ids_json":("STRING",{"default":"[]","multiline":True})}}
    def checkpoint(self,execution_plan,completed_ids_json,failed_ids_json):
        result=queue_checkpoint(execution_plan,completed_ids_json,failed_ids_json); return result,stable_json(result,indent=2),result["remaining_count"]

NODE_CLASS_MAPPINGS={"CDVerifyPackage":CDVerifyPackage,"CDMigratePayload":CDMigratePayload,"CDRetryPolicy":CDRetryPolicy,"CDQueueCheckpoint":CDQueueCheckpoint}
NODE_DISPLAY_NAME_MAPPINGS={"CDVerifyPackage":"CD · Verify Package","CDMigratePayload":"CD · Migrate Payload","CDRetryPolicy":"CD · Retry Policy","CDQueueCheckpoint":"CD · Queue Checkpoint"}
