"""TDD tests for drawio_service — generate_diagram, validate_xml, generate_viewer_url.

Tests (12 total):
 Original 4:
  1. test_generate_diagram_returns_xml_string - returns str with mxGraphModel and mxCell tags
  2. test_generate_diagram_contains_component_names - component names appear in XML
  3. test_generate_diagram_empty_components - empty list returns valid XML with mxGraphModel
  4. test_generate_diagram_title_in_xml - title string appears in returned XML

 New 8 (validate_xml, generate_viewer_url, typed shapes, directional edges):
  5. test_validate_xml_valid - validate_xml returns True for well-formed XML
  6. test_validate_xml_malformed - validate_xml returns False for unclosed tags
  7. test_validate_xml_empty_string - validate_xml returns False for empty string
  8. test_generate_viewer_url_prefix - URL starts with https://app.diagrams.net/?xml=
  9. test_generate_viewer_url_encodes_xml - special chars are percent-encoded in URL
 10. test_typed_shape_database - "User Database" component uses database shape style
 11. test_typed_shape_external - "External System" component uses rhombus shape style
 12. test_directional_edge_in_xml - edges include endArrow=block in style

No external dependencies — drawio_service uses Python stdlib only.
"""

import pytest

from services.drawio_service import (
    generate_diagram,
    generate_viewer_url,
    validate_xml,
)


# ---------------------------------------------------------------------------
# Original tests (4)
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


# ---------------------------------------------------------------------------
# New tests: validate_xml (3)
# ---------------------------------------------------------------------------


def test_validate_xml_valid():
    """validate_xml returns True for well-formed XML output of generate_diagram."""
    xml = generate_diagram("T", ["A"], [])
    assert validate_xml(xml) is True


def test_validate_xml_malformed():
    """validate_xml returns False for malformed XML (unclosed tags) without raising."""
    assert validate_xml("<mxGraphModel><root>") is False


def test_validate_xml_empty_string():
    """validate_xml returns False for empty string without raising."""
    assert validate_xml("") is False


# ---------------------------------------------------------------------------
# New tests: generate_viewer_url (2)
# ---------------------------------------------------------------------------


def test_generate_viewer_url_prefix():
    """generate_viewer_url returns URL starting with https://app.diagrams.net/?xml=."""
    url = generate_viewer_url("<mxGraphModel/>")
    assert url.startswith("https://app.diagrams.net/?xml=")


def test_generate_viewer_url_encodes_xml():
    """generate_viewer_url percent-encodes XML special characters in the URL."""
    url = generate_viewer_url("<tag>")
    assert "%" in url


# ---------------------------------------------------------------------------
# New tests: typed shapes and directional edges (3)
# ---------------------------------------------------------------------------


def test_typed_shape_database():
    """Component named 'User Database' produces XML with database shape style."""
    result = generate_diagram("T", ["User Database"], [])
    assert "shape=mxgraph.flowchart.database" in result


def test_typed_shape_external():
    """Component named 'External System' produces XML with rhombus shape style."""
    result = generate_diagram("T", ["External System"], [])
    assert "rhombus" in result


def test_directional_edge_in_xml():
    """Edge cells produced by generate_diagram include endArrow=block in style."""
    result = generate_diagram("T", ["A", "B"], [("A", "B")])
    assert "endArrow=block" in result
