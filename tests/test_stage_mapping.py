import pytest

from app.stages import map_status_to_stage
from tests.fixtures.stage_map_cases import STAGE_MAP_CASES

# Examples straight from the spec's documented rule table (§7.1), including the
# two ordering-sensitive cases called out explicitly: "size set" must beat a
# generic "cutting" match, and "finishing" must beat a generic "washing" match.
SPEC_RULE_EXAMPLES = [
    ("FI Done", "FI Done"),
    ("Under Shrinkage", "Under Shrinkage"),
    ("Fabric Received", "Fabric Received"),
    ("PP to send", "Size Set / PP Approval"),
    ("PP Approval", "Size Set / PP Approval"),
    ("Size Set", "Size Set / PP Approval"),
    ("size set under cutting", "Size Set / PP Approval"),
    ("Bulk Pattern", "Bulk Pattern"),
    ("Issued for Cutting", "Issued for Cutting"),
    ("Rechecking", "Under Finishing"),
    ("Under Washing / Finishing", "Under Finishing"),
    ("Under Loading", "Under Loading"),
    ("Under Washing", "Under Washing"),
    ("Under Assembly", "Under Assembly"),
    ("Emb", "Under Embroidery"),
    ("Under Sewing", "Under Sewing"),
    ("front ready back pending", "Under Sewing"),
    ("Under Cutting", "Under Cutting"),
]


@pytest.mark.parametrize("raw,expected", SPEC_RULE_EXAMPLES)
def test_spec_rule_examples(raw, expected):
    assert map_status_to_stage(raw) == expected


@pytest.mark.parametrize("raw,expected", STAGE_MAP_CASES)
def test_real_stage_map_cases(raw, expected):
    assert map_status_to_stage(raw) == expected


def test_blank_and_total_are_not_guessed():
    assert map_status_to_stage("") is None
    assert map_status_to_stage(None) is None


def test_unrecognized_status_flagged_not_guessed():
    assert map_status_to_stage("some totally unknown phrase") is None
