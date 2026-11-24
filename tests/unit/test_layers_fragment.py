"""Contracts for projecting the all-layers style reference fragment."""

import pytest

from scripts.style.gen_style import fragment
from skippercast.style import load_layers


@pytest.mark.parametrize("change_z", [False, True], ids=["same-z", "different-z"])
def test_fragment_refuses_duplicate_slot_id(change_z):
    # A last-write-wins map accepts identical duplicates and can silently move
    # a whole slot's layers when the second row has a different z.
    tokens = load_layers()
    stack = tokens["stacking"]
    slots = stack["z_order"]
    slot = next(row for row in slots if row["id"] == "color-field")
    duplicate = dict(slot)
    if change_z:
        duplicate["z"] = max(row["z"] for row in slots) + 1
    copied = {**tokens, "stacking": {**stack, "z_order": (*slots, duplicate)}}

    with pytest.raises(ValueError, match="duplicate.*color-field"):
        fragment(copied)
