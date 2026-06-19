from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "continuity_director_smoke"


def load_package():
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to create package spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    package = load_package()
    mappings = package.NODE_CLASS_MAPPINGS
    displays = package.NODE_DISPLAY_NAME_MAPPINGS
    assert mappings, "NODE_CLASS_MAPPINGS is empty"
    assert set(mappings) == set(displays), "display mappings do not match node mappings"
    assert package.WEB_DIRECTORY == "./js"
    for name, node_class in mappings.items():
        inputs = node_class.INPUT_TYPES()
        assert isinstance(inputs, dict), f"{name}.INPUT_TYPES did not return a dict"
        assert hasattr(node_class, "FUNCTION"), f"{name} has no FUNCTION"
        assert hasattr(node_class, "RETURN_TYPES"), f"{name} has no RETURN_TYPES"
        instance = node_class()
        assert callable(getattr(instance, node_class.FUNCTION)), f"{name} function is not callable"
    print(f"ComfyUI lifecycle smoke passed: {len(mappings)} nodes, WEB_DIRECTORY={package.WEB_DIRECTORY}")


if __name__ == "__main__":
    main()
