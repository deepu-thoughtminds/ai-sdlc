"""Mention parser: extracts @jarvis mentions from Jira comment text.

Threat mitigations applied:
- T-02-02: Uses re.search with a bounded pattern; no eval or shell interpolation.
- T-02-05: Stage is validated against KNOWN_STAGES; unknown stages return None.

Note: Jira's Atlassian Document Format (ADF) may wrap mention nodes
differently. For the Walking Skeleton, comment body is treated as plain
text. ADF parsing ships in Phase 3.
"""

import re
from dataclasses import dataclass, field

KNOWN_STAGES = {"describe", "architecture", "assign", "codegen", "testgen"}


@dataclass
class MentionResult:
    """Result of a successful @jarvis mention parse."""

    mention_target: str  # "jarvis"
    stage: str  # "describe" | "architecture" | "assign" | "codegen" | "testgen"
    extra: str = ""  # any trailing tokens after the stage keyword


def parse_mention(comment_body: str) -> MentionResult | None:
    """Parse @<agent> <stage> [extra] from a comment body string.

    Returns MentionResult if a valid @jarvis mention with a known stage is
    found; returns None if no mention exists or the stage is unrecognised.

    Args:
        comment_body: Raw comment text (plain string for Walking Skeleton).

    Returns:
        MentionResult or None.
    """
    match = re.search(r"@(\w+)\s+(\w[\w-]*)(.*)", comment_body)
    if not match:
        return None

    mention_target = match.group(1)
    stage_raw = match.group(2).lower()
    extra = match.group(3).strip()

    if stage_raw not in KNOWN_STAGES:
        return None  # silently ignore unknown commands (T-02-05)

    return MentionResult(mention_target=mention_target, stage=stage_raw, extra=extra)
