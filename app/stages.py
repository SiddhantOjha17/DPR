STAGE_RULES: list[tuple[list[str], str]] = [
    (["fi done"], "FI Done"),
    (["shrinkage"], "Under Shrinkage"),
    (["fabric received"], "Fabric Received"),
    (["pp ", "pp approval", "pp to send"], "Size Set / PP Approval"),
    (["size set"], "Size Set / PP Approval"),
    (["bulk pattern"], "Bulk Pattern"),
    (["issued for cutting"], "Issued for Cutting"),
    (["rechecking", "finishing"], "Under Finishing"),
    (["loading"], "Under Loading"),
    (["washing"], "Under Washing"),
    (["assembly"], "Under Assembly"),
    (["emb"], "Under Embroidery"),
    (["sew", "front", "back"], "Under Sewing"),
    (["cutting"], "Under Cutting"),
]


def map_status_to_stage(raw: str | None) -> str | None:
    """Case-insensitive ordered substring match. First rule to match wins.
    Returns None (flag for manual review) if nothing matches - never guesses."""
    if not raw:
        return None
    lowered = raw.lower()
    for patterns, stage_name in STAGE_RULES:
        if any(pattern in lowered for pattern in patterns):
            return stage_name
    return None
