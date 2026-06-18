"""TDD tests for drawio_service.generate_diagram().

Tests (4 total):
1. test_generate_diagram_returns_xml_string - returns str with mxGraphModel and mxCell tags
2. test_generate_diagram_contains_component_names - component names appear in XML
3. test_generate_diagram_empty_components - empty list returns valid XML with mxGraphModel
4. test_generate_diagram_title_in_xml - title string appears in returned XML

No external dependencies — generate_diagram uses Python stdlib only.
"""

import pytest

from services.drawio_service import generate_diagram


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_diagram_returns_xml_string():
    """generate_diagram returns a str containing mxGraphModel and mxCell tags."""
    result = generate_diagram(
        "Option A",
        ["API Gateway", "Auth Service"],
        [("API Gateway", "Auth Service")],
    )
    assert isinstance(result, str)
    assert "<mxGraphModel" in result
    assert "mxCell" in result


def test_generate_diagram_contains_component_names():
    """Component names appear in the returned XML."""
    result = generate_diagram(
        "Option A",
        ["API Gateway", "Auth Service"],
        [("API Gateway", "Auth Service")],
    )
    assert "API Gateway" in result
    assert "Auth Service" in result


def test_generate_diagram_empty_components():
    """generate_diagram with empty component list returns valid XML with mxGraphModel."""
    result = generate_diagram("Empty", [], [])
    assert isinstance(result, str)
    assert "<mxGraphModel" in result


def test_generate_diagram_title_in_xml():
    """The title string appears somewhere in the returned XML."""
    result = generate_diagram(
        "Option A",
        ["API Gateway", "Auth Service"],
        [("API Gateway", "Auth Service")],
    )
    assert "Option A" in result
