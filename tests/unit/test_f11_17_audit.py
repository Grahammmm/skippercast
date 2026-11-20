"""F11-17: schema kind literals must not silently shadow one another."""
import ast
from collections import Counter

from skippercast import validate
from tests._support import ROOT


def test_schema_kind_registry_has_no_duplicate_keys():
    # Inspect the literal before Python collapses repeated keys at import time.
    module = ast.parse((ROOT / "src/skippercast/validate.py").read_text(encoding="utf-8"))
    registry = next(
        node.value for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "KINDS" for target in node.targets)
    )
    assert isinstance(registry, ast.Dict)
    assert all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in registry.keys)
    keys = Counter(key.value for key in registry.keys if isinstance(key, ast.Constant))
    assert {key: count for key, count in keys.items() if count > 1} == {}


def test_coast_recipe_kind_still_selects_its_schema():
    # Removing the registration entirely would also eliminate the duplicate.
    schema = validate.validator("coast-recipe-v1").schema
    assert schema["$id"] == "https://skippercast.com/schemas/coast-recipe-v1.schema.json"
