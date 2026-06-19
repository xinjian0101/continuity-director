from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity_core import (  # noqa: E402
    audit_manifests,
    build_character,
    build_project,
    build_scene,
    build_shot,
    provider_payload,
)


def main() -> None:
    project = build_project(
        "地下车库短片",
        20260619,
        "9:16",
        24,
        "cinematic realistic photography, natural skin texture",
        "cold gray with restrained red accents",
        "stable cold ceiling light and red rim light from camera right",
    )
    character = build_character(
        project,
        "hero-01",
        "林默",
        "20-year-old Chinese man, recognizable natural face",
        "oval face, straight eyebrows, small scar near right eyebrow",
        "short slightly messy black hair",
        "slim athletic build",
        "dark charcoal hooded jacket, black T-shirt, dark cargo pants",
        "silver analog watch on left wrist",
        "scar remains on right eyebrow, watch remains on left wrist",
    )
    scene = build_scene(
        project,
        character,
        "garage-01",
        "abandoned underground parking garage",
        "late night",
        "heavy rain outside",
        "cold fluorescent lights, weak red emergency light from camera right",
        "wet floor, numbered pillars, damaged sedan at pillar B7",
        "moves screen left to screen right",
        "damaged sedan, red fire cabinet, yellow floor line",
    )
    shot_1 = build_shot(
        project,
        character,
        scene,
        "shot-001",
        5,
        "walks toward the damaged sedan and raises a flashlight",
        "restrained tension",
        "",
        "medium shot",
        "slow dolly in",
        "35mm",
        "character on left third, damaged sedan in background",
        "natural walking pace, stable hands",
        allowed_changes="emotion, position",
        position="near pillar B6, facing screen right",
    )
    shot_2 = build_shot(
        project,
        character,
        scene,
        "shot-002",
        5,
        "stops beside the sedan and looks through the broken window",
        "controlled fear",
        "里面有人吗？",
        "medium close-up",
        "locked camera",
        "50mm",
        "face on left third, broken window foreground",
        "subtle breathing, no facial morphing",
        previous_shot=shot_1,
        allowed_changes="emotion, position",
        position="beside the driver-side window, facing screen right",
    )

    output = ROOT / "examples" / "demo-output.json"
    output.write_text(
        json.dumps(
            {
                "project": project,
                "character": character,
                "scene": scene,
                "shot_1": shot_1,
                "shot_2": shot_2,
                "audit": audit_manifests(shot_1, shot_2),
                "veo_export": provider_payload(shot_2, "veo"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
