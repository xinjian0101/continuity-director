"""ComfyUI nodes for continuity planning and production governance."""
from __future__ import annotations
from typing import Any

from .collaboration_core import three_way_merge
from .continuity_core import audit_event, build_lock, build_manifest, continuity_diff, package_payload, parse_json, split_csv, stable_json
from .production_core import expand_storyboard, quality_gate, rank_takes, reference_handoff
from .runtime_core import build_execution_plan

LOCKS="Continuity Director/01 Locks"; DIRECT="Continuity Director/02 Directing"; QC="Continuity Director/03 Quality"
RUNTIME="Continuity Director/04 Runtime"; COLLAB="Continuity Director/05 Collaboration"; EXPORT="Continuity Director/06 Export"
def js(v): return stable_json(v, indent=2)

class CDProjectLock:
    RETURN_TYPES=("CD_PROJECT","STRING","STRING"); RETURN_NAMES=("project","project_json","project_hash"); FUNCTION="build"; CATEGORY=LOCKS
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"project_id":("STRING",{"default":"project-001"}),"title":("STRING",{"default":"Untitled Production"}),"aspect_ratio":(["16:9","9:16","1:1","4:3","21:9"],),"fps":("INT",{"default":24,"min":1,"max":240}),"interface_language":(["en","zh-CN","bilingual"],),"notes":("STRING",{"default":"","multiline":True})}}
    def build(self,project_id,title,aspect_ratio,fps,interface_language,notes):
        r=build_lock("project",project_id,{"title":title.strip(),"aspect_ratio":aspect_ratio,"fps":int(fps),"interface_language":interface_language,"notes":notes.strip()}); return r,js(r),r["hash"]

class CDCharacterLock:
    RETURN_TYPES=("CD_CHARACTER","STRING","STRING"); RETURN_NAMES=("character","character_json","character_hash"); FUNCTION="build"; CATEGORY=LOCKS
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"character_id":("STRING",{"default":"character-001"}),"display_name":("STRING",{"default":"Lead"}),"appearance":("STRING",{"default":"","multiline":True}),"wardrobe":("STRING",{"default":"","multiline":True}),"forbidden_changes":("STRING",{"default":"hair color, facial structure","multiline":True}),"reference_ids":("STRING",{"default":"","multiline":True}),"identity_seed":("INT",{"default":1,"min":0,"max":2147483647})}}
    def build(self,character_id,display_name,appearance,wardrobe,forbidden_changes,reference_ids,identity_seed):
        r=build_lock("character",character_id,{"display_name":display_name.strip(),"appearance":appearance.strip(),"wardrobe":wardrobe.strip(),"forbidden_changes":split_csv(forbidden_changes),"reference_ids":split_csv(reference_ids),"identity_seed":int(identity_seed)}); return r,js(r),r["hash"]

class CDSceneLock:
    RETURN_TYPES=("CD_SCENE","STRING","STRING"); RETURN_NAMES=("scene","scene_json","scene_hash"); FUNCTION="build"; CATEGORY=LOCKS
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"scene_id":("STRING",{"default":"scene-001"}),"location":("STRING",{"default":""}),"time_of_day":(["dawn","day","sunset","night","interior-controlled"],),"lighting":("STRING",{"default":"soft natural light","multiline":True}),"palette":("STRING",{"default":"neutral","multiline":True}),"environment_notes":("STRING",{"default":"","multiline":True})}}
    def build(self,scene_id,location,time_of_day,lighting,palette,environment_notes):
        r=build_lock("scene",scene_id,{"location":location.strip(),"time_of_day":time_of_day,"lighting":lighting.strip(),"palette":palette.strip(),"environment_notes":environment_notes.strip()}); return r,js(r),r["hash"]

class CDShotLock:
    RETURN_TYPES=("CD_SHOT","STRING","STRING"); RETURN_NAMES=("shot","shot_json","shot_hash"); FUNCTION="build"; CATEGORY=LOCKS
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"shot_id":("STRING",{"default":"shot-001"}),"prompt":("STRING",{"default":"","multiline":True}),"negative_prompt":("STRING",{"default":"","multiline":True}),"camera":("STRING",{"default":"medium shot, eye level","multiline":True}),"duration_seconds":("FLOAT",{"default":3.0,"min":0.1,"max":600.0,"step":0.1}),"seed":("INT",{"default":1,"min":0,"max":2147483647})},"optional":{"project":("CD_PROJECT",),"scene":("CD_SCENE",),"character":("CD_CHARACTER",)}}
    def build(self,shot_id,prompt,negative_prompt,camera,duration_seconds,seed,project=None,scene=None,character=None):
        r=build_lock("shot",shot_id,{"project_id":(project or {}).get("id"),"scene_id":(scene or {}).get("id"),"character_ids":[character.get("id")] if character else [],"prompt":prompt.strip(),"negative_prompt":negative_prompt.strip(),"camera":camera.strip(),"duration_seconds":float(duration_seconds),"seed":int(seed)}); return r,js(r),r["hash"]

class CDManifestBuilder:
    RETURN_TYPES=("CD_MANIFEST","STRING","STRING"); RETURN_NAMES=("manifest","manifest_json","manifest_hash"); FUNCTION="build"; CATEGORY=LOCKS
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"project":("CD_PROJECT",)},"optional":{"character":("CD_CHARACTER",),"scene":("CD_SCENE",),"shot":("CD_SHOT",),"extra_characters_json":("STRING",{"default":"[]","multiline":True}),"extra_scenes_json":("STRING",{"default":"[]","multiline":True}),"extra_shots_json":("STRING",{"default":"[]","multiline":True})}}
    def build(self,project,character=None,scene=None,shot=None,extra_characters_json="[]",extra_scenes_json="[]",extra_shots_json="[]"):
        chars=parse_json(extra_characters_json,default=[],expected=list); scenes=parse_json(extra_scenes_json,default=[],expected=list); shots=parse_json(extra_shots_json,default=[],expected=list)
        if character: chars.insert(0,character)
        if scene: scenes.insert(0,scene)
        if shot: shots.insert(0,shot)
        r=build_manifest(project,chars,scenes,shots); return r,js(r),r["hash"]

class CDBatchDirector:
    RETURN_TYPES=("CD_SHOT_CHAIN","STRING","INT"); RETURN_NAMES=("shot_chain","shot_chain_json","take_count"); FUNCTION="direct"; CATEGORY=DIRECT
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"manifest":("CD_MANIFEST",),"storyboard_json":("STRING",{"default":"[{\"id\":\"shot-001\",\"prompt\":\"Opening shot\"}]","multiline":True}),"takes_per_shot":("INT",{"default":3,"min":1,"max":16}),"base_seed":("INT",{"default":1000,"min":0,"max":2147483647})}}
    def direct(self,manifest,storyboard_json,takes_per_shot,base_seed): r=expand_storyboard(storyboard_json,manifest,base_seed,takes_per_shot); return r,js(r),r["take_count"]

class CDReferenceHandoff:
    RETURN_TYPES=("CD_REFERENCE","STRING"); RETURN_NAMES=("reference_handoff","reference_json"); FUNCTION="handoff"; CATEGORY=DIRECT
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"previous_reference_json":("STRING",{"default":"{}","multiline":True}),"next_reference_json":("STRING",{"default":"{}","multiline":True}),"strategy":(["last_to_first","shared_anchor","manual"],)}}
    def handoff(self,previous_reference_json,next_reference_json,strategy): r=reference_handoff(previous_reference_json,next_reference_json,strategy); return r,js(r)

class CDQualityGate:
    RETURN_TYPES=("BOOLEAN","STRING","STRING"); RETURN_NAMES=("passed","gate_json","failed_metrics"); FUNCTION="evaluate"; CATEGORY=QC
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"metrics_json":("STRING",{"default":"{\"identity\":0.9,\"continuity\":0.82,\"technical\":0.88}","multiline":True}),"thresholds_json":("STRING",{"default":"{\"identity\":0.78,\"continuity\":0.72,\"technical\":0.70}","multiline":True}),"mode":(["all","any"],)}}
    def evaluate(self,metrics_json,thresholds_json,mode): r=quality_gate(metrics_json,thresholds_json,mode); return r["passed"],js(r),", ".join(r["failed_metrics"])

class CDTakeRanker:
    RETURN_TYPES=("STRING","STRING","FLOAT"); RETURN_NAMES=("best_take_id","ranking_json","best_score"); FUNCTION="rank"; CATEGORY=QC
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"takes_json":("STRING",{"default":"[{\"take_id\":\"take-01\",\"metrics\":{\"identity\":0.9}}]","multiline":True}),"weights_json":("STRING",{"default":"{\"identity\":0.35,\"continuity\":0.25,\"technical\":0.2,\"motion\":0.1,\"prompt\":0.1}","multiline":True})}}
    def rank(self,takes_json,weights_json):
        r=rank_takes(takes_json,weights_json); b=r[0] if r else {"take_id":"","score":0.0}; return b["take_id"],js(r),float(b["score"])

class CDContinuityReport:
    RETURN_TYPES=("BOOLEAN","STRING","INT"); RETURN_NAMES=("passed","report_json","issue_count"); FUNCTION="compare"; CATEGORY=QC
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"expected_json":("STRING",{"default":"{}","multiline":True}),"actual_json":("STRING",{"default":"{}","multiline":True}),"ignore_paths":("STRING",{"default":"$.timestamp,$.hash","multiline":True})}}
    def compare(self,expected_json,actual_json,ignore_paths):
        issues=continuity_diff(parse_json(expected_json,default={}),parse_json(actual_json,default={}),split_csv(ignore_paths)); r={"passed":not issues,"issue_count":len(issues),"issues":issues}; return not issues,js(r),len(issues)

class CDExecutionPlan:
    RETURN_TYPES=("CD_EXECUTION_PLAN","STRING","INT"); RETURN_NAMES=("execution_plan","execution_plan_json","wave_count"); FUNCTION="plan"; CATEGORY=RUNTIME
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"shot_chain":("CD_SHOT_CHAIN",),"max_parallel":("INT",{"default":4,"min":1,"max":64})}}
    def plan(self,shot_chain,max_parallel): r=build_execution_plan(shot_chain,max_parallel); return r,js(r),r["wave_count"]

class CDAuditEvent:
    RETURN_TYPES=("CD_AUDIT_EVENT","STRING","STRING"); RETURN_NAMES=("audit_event","audit_json","audit_hash"); FUNCTION="append"; CATEGORY=COLLAB
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"event_type":("STRING",{"default":"generation-approved"}),"actor":("STRING",{"default":"local-user"}),"payload_json":("STRING",{"default":"{}","multiline":True}),"previous_hash":("STRING",{"default":""})}}
    def append(self,event_type,actor,payload_json,previous_hash): r=audit_event(event_type,actor,parse_json(payload_json,default={}),previous_hash); return r,js(r),r["hash"]

class CDThreeWayMerge:
    RETURN_TYPES=("STRING","STRING","BOOLEAN"); RETURN_NAMES=("merged_json","conflicts_json","has_conflicts"); FUNCTION="merge"; CATEGORY=COLLAB
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"base_json":("STRING",{"default":"{}","multiline":True}),"current_json":("STRING",{"default":"{}","multiline":True}),"incoming_json":("STRING",{"default":"{}","multiline":True})}}
    def merge(self,base_json,current_json,incoming_json): m,c=three_way_merge(base_json,current_json,incoming_json); return js(m),js(c),bool(c)

class CDExportPackage:
    RETURN_TYPES=("STRING","STRING"); RETURN_NAMES=("package_json","package_hash"); FUNCTION="export"; CATEGORY=EXPORT
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"manifest":("CD_MANIFEST",)},"optional":{"shot_chain":("CD_SHOT_CHAIN",),"execution_plan":("CD_EXECUTION_PLAN",),"audit_event":("CD_AUDIT_EVENT",)}}
    def export(self,manifest,shot_chain=None,execution_plan=None,audit_event=None): r=package_payload(manifest=manifest,shot_chain=shot_chain,execution_plan=execution_plan,audit_event=audit_event); return js(r),r["hash"]

NODE_CLASS_MAPPINGS={"CDProjectLock":CDProjectLock,"CDCharacterLock":CDCharacterLock,"CDSceneLock":CDSceneLock,"CDShotLock":CDShotLock,"CDManifestBuilder":CDManifestBuilder,"CDBatchDirector":CDBatchDirector,"CDReferenceHandoff":CDReferenceHandoff,"CDQualityGate":CDQualityGate,"CDTakeRanker":CDTakeRanker,"CDContinuityReport":CDContinuityReport,"CDExecutionPlan":CDExecutionPlan,"CDAuditEvent":CDAuditEvent,"CDThreeWayMerge":CDThreeWayMerge,"CDExportPackage":CDExportPackage}
NODE_DISPLAY_NAME_MAPPINGS={k:"CD · "+v for k,v in {"CDProjectLock":"Project Lock","CDCharacterLock":"Character Lock","CDSceneLock":"Scene Lock","CDShotLock":"Shot Lock","CDManifestBuilder":"Manifest Builder","CDBatchDirector":"Batch Director","CDReferenceHandoff":"Reference Handoff","CDQualityGate":"Quality Gate","CDTakeRanker":"Take Ranker","CDContinuityReport":"Continuity Report","CDExecutionPlan":"Execution Plan","CDAuditEvent":"Audit Event","CDThreeWayMerge":"Three-Way Merge","CDExportPackage":"Export Package"}.items()}
