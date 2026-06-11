#!/usr/bin/env python3
"""Export glossary v2 automatic terms to a runtime JSON file."""

import json
import os
from pathlib import Path

from notion_config import load_local_env


load_local_env()

import collect  # noqa: E402


OUT = Path("data/glossary_runtime.json")


def main():
    runtime = collect.load_glossary_v2()
    output = {
        "generated_by": "build_glossary_runtime.py",
        "glossary_v2_db_id": collect.GLOSSARY_V2_DB_ID,
        **runtime,
    }
    os.makedirs(OUT.parent, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(
        f"用語集runtime生成完了: alias {len(output['alias_map'])} / "
        f"exclude {len(output['exclude_keywords'])} / "
        f"experience {len(output['experience_keywords'])} / "
        f"songs {len(output['song_terms'])} -> {OUT}"
    )


if __name__ == "__main__":
    main()
