"""Programmatic drawio (mxGraph XML) diagram generator for architecture options.

Generates simple box-and-arrow diagrams. MVP implementation — upgradeable to full
drawio skill (Agents365-ai/drawio-skill) in a future phase.

No external dependencies — uses Python string formatting only.

Threat mitigations:
  T-04-04: Diagram XML is generated programmatically from component name strings
           (no user-exec path); XML is embedded in Confluence <pre> blocks, not executed.
"""


def generate_diagram(
    title: str,
    components: list[str],
    connections: list[tuple[str, str]],
) -> str:
    """Generate mxGraph XML for a drawio diagram.

    Assigns each component a unique integer cell id starting at 2
    (id=0 is the root container, id=1 is the default parent layer).
    Includes the title as a label cell with id="title_cell".

    Layout:
    - Components laid out in a grid: 3 columns, 200px horizontal spacing,
      120px vertical spacing, starting at x=40, y=40.
    - Connections are (src_label, dst_label) tuples; edges skipped when either
      end label is not in the component list.

    Args:
        title: Diagram title — rendered as a label cell above the grid.
        components: List of component/service name strings.
        connections: List of (source_label, target_label) tuples for edges.

    Returns:
        Full mxGraph XML string (no extra dependencies — stdlib string formatting).
    """
    # Build cell_ids dict: component_name → integer cell id (starting at 2)
    cell_ids: dict[str, int] = {}
    for idx, name in enumerate(components):
        cell_ids[name] = idx + 2  # id=0 and id=1 are reserved

    # --- Assemble XML via string building ---
    cells: list[str] = []

    # Title label cell (id=1 is parent layer; title uses a special id)
    title_escaped = _escape_xml(title)
    cells.append(
        f'<mxCell id="title_cell" value="{title_escaped}" vertex="1" parent="1" '
        f'style="text;html=1;strokeColor=none;fillColor=none;align=center;'
        f'verticalAlign=middle;whiteSpace=wrap;rounded=0;">'
        f'<mxGeometry x="0" y="-40" width="500" height="30" as="geometry"/>'
        f'</mxCell>'
    )

    # Component vertex cells — grid layout: 3 per row
    for idx, name in enumerate(components):
        cell_id = cell_ids[name]
        col = idx % 3
        row = idx // 3
        x = 40 + col * 200
        y = 40 + row * 120
        name_escaped = _escape_xml(name)
        cells.append(
            f'<mxCell id="{cell_id}" value="{name_escaped}" '
            f'style="rounded=1;whiteSpace=wrap;html=1;" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="160" height="60" as="geometry"/>'
            f'</mxCell>'
        )

    # Edge cells — sequential id starting at len(components) + 2
    edge_id_start = len(components) + 2
    for edge_idx, (src_label, dst_label) in enumerate(connections):
        if src_label not in cell_ids or dst_label not in cell_ids:
            # Skip edges where either endpoint is not a known component
            continue
        edge_id = edge_id_start + edge_idx
        src_id = cell_ids[src_label]
        dst_id = cell_ids[dst_label]
        cells.append(
            f'<mxCell id="{edge_id}" value="" edge="1" '
            f'source="{src_id}" target="{dst_id}" parent="1">'
            f'<mxGeometry relative="1" as="geometry"/>'
            f'</mxCell>'
        )

    # Assemble the final mxGraphModel XML
    cells_xml = "\n".join(cells)
    xml = (
        f'<mxGraphModel>'
        f'<root>'
        f'<mxCell id="0"/>'
        f'<mxCell id="1" parent="0"/>'
        f'{cells_xml}'
        f'</root>'
        f'</mxGraphModel>'
    )
    return xml


def _escape_xml(text: str) -> str:
    """Escape special characters for use in XML attribute values."""
    return (
        text
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
