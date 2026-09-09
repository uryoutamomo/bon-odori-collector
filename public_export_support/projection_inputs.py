"""Explicit auxiliary values consumed by the public projection."""

from dataclasses import dataclass
from pathlib import Path
import json

from public_export_support.historical_references import fixed_rule_key


@dataclass(frozen=True)
class PublicProjectionInputs:
    prediction_payload: dict
    overrides: dict
    fixed_date_rules: dict


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def fixed_date_rules_from_payload(payload):
    rules = {}
    for row in payload.get("rules") or []:
        key = fixed_rule_key(row.get("name"), row.get("venue"))
        if key[0] and key[1]:
            rules[key] = row
    return rules
