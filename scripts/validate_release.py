from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = pyproject["project"]["version"]

    sys.path.insert(0, str(ROOT))
    from continuity_core import PACKAGE_VERSION  # noqa: PLC0415

    if project_version != PACKAGE_VERSION:
        raise SystemExit(f"Version mismatch: pyproject={project_version}, core={PACKAGE_VERSION}")

    package_name = "continuity_director_plugin"
    spec = importlib.util.spec_from_file_location(
        package_name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise SystemExit("Unable to create package import spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)

    mappings = module.NODE_CLASS_MAPPINGS
    if len(mappings) < 95:
        raise SystemExit(f"Expected at least 95 nodes, found {len(mappings)}")
    if module.WEB_DIRECTORY != "./js":
        raise SystemExit("WEB_DIRECTORY is invalid")

    required = {
        "CDOneClickDirector",
        "CDBatchDirector",
        "CDSequenceAudit",
        "CDManifestValidator",
        "CDManifestMigrate",
        "CDPackageProject",
        "CDCastLock",
        "CDTakeVariants",
        "CDSequenceRepair",
        "CDProductionReport",
        "CDPackageVerify",
        "CDWorkflowTemplate",
        "CDRunSnapshot",
        "CDQueueState",
        "CDQualityEvaluate",
        "CDRunBundleVerify",
        "CDMediaProbe",
        "CDTechnicalQC",
        "CDBoundaryContinuity",
        "CDAssemblyExecute",
        "CDVersionSnapshot",
        "CDBatchRerunPlan",
        "CDResourceQuota",
        "CDRegressionCompare",
        "CDLineageGraph",
        "CDCollaborationManifest",
        "CDEditLockAcquire",
        "CDApprovalTransition",
        "CDAuditVerify",
        "CDDistributedSchedule",
        "CDCompatibilityMatrix",
        "CDFaultInjectionPlan",
        "CDReplayCompare",
        "CDGenerationReleaseGate",
    }
    missing = required - set(mappings)
    if missing:
        raise SystemExit(f"Missing node mappings: {sorted(missing)}")

    print(f"Release validation passed: v{PACKAGE_VERSION}, {len(mappings)} nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
