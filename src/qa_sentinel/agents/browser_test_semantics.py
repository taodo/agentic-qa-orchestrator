"""Closed human-QA grammar. No model inference, selectors or execution authority."""
import json
import re
from typing import Literal
from qa_sentinel.domain.campaign_content import Frozen
from qa_sentinel.domain.browser_grounding import GroundingLimitation


class Outcome(Frozen):
    kind: Literal["PAGE_LOAD", "HEADING_VISIBLE", "HEADING_TEXT"]
    text: str | None = None


QUOTE = r'("(?:[^"\\]|\\.)*")'

def outcome(expected):
    if re.fullmatch(r"(?:The )?(?:home )?page loads successfully\.?", expected, re.I):
        return Outcome(kind="PAGE_LOAD")
    match = re.fullmatch(r'(?:The )?(?:main )?heading ' + QUOTE + r' is (?:visible|visibly displayed)\.?', expected, re.I)
    if match:
        return Outcome(kind="HEADING_VISIBLE", text=json.loads(match[1]))
    match = re.fullmatch(r'(?:The )?(?:main )?heading (?:reads|displays) ' + QUOTE + r'\.?', expected, re.I)
    if match:
        return Outcome(kind="HEADING_VISIBLE" if " displays " in expected.casefold() else "HEADING_TEXT", text=json.loads(match[1]))
    return None


def validate_summary(test):
    """Legacy literal summaries stay compatible; new summaries must cover every claim."""
    if test.overall_expected_result in {s.expected for s in test.steps}:
        return
    # Exact conjunction of all complete step outcomes is a bounded composition.
    normalized = lambda text: text.strip().rstrip(".")
    if test.overall_expected_result and normalized(test.overall_expected_result) == " and ".join(normalized(s.expected or "") for s in test.steps):
        return
    match = re.fullmatch(r'The (.+?) home page loads successfully and visibly displays the (?:main )?heading ' + QUOTE + r'\.?', test.overall_expected_result or "", re.I)
    outcomes = [outcome(s.expected or "") for s in test.steps]
    if match and len(test.steps) == 2 and outcomes == [Outcome(kind="PAGE_LOAD"), Outcome(kind="HEADING_VISIBLE", text=json.loads(match[2]))]:
        # A named home page means the configured Target, never an invented route/site.
        if re.fullmatch(r'(?:Open|Visit|Navigate to) the ' + re.escape(match[1]) + r' home page\.?', test.steps[0].action, re.I):
            return
    raise GroundingLimitation("INSUFFICIENT_TEST_INFORMATION")


def assertion_for(step):
    parsed = outcome(step.expected or "")
    if parsed is None:
        return None
    if parsed.kind == "PAGE_LOAD":
        if not re.fullmatch(r'(?:Open|Visit|Navigate to) the (?:(?:[^./:]+? )?home )?page\.?', step.action, re.I):
            raise GroundingLimitation("INSUFFICIENT_TEST_INFORMATION", step.index)
    else:
        heading_action = re.fullmatch(r'(?:Observe|Verify|Assert) (?:the )?(?:main )?heading(?: on the loaded page)?\.?', step.action, re.I)
        # This wording explicitly claims visibility; a text-only outcome cannot drop it.
        visible_heading_action = parsed.kind == "HEADING_VISIBLE" and re.fullmatch(
            r'(?:Observe|Verify|Assert) (?:the )?visible page heading\.?', step.action, re.I)
        if not (heading_action or visible_heading_action):
            raise GroundingLimitation("INSUFFICIENT_TEST_INFORMATION", step.index)
    if parsed.text is not None and not parsed.text:
        raise GroundingLimitation("INSUFFICIENT_TEST_INFORMATION", step.index)
    return parsed
