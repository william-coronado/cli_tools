from __future__ import annotations

import xml.etree.ElementTree as ET


def summarize_xml(content: str, max_depth: int = 4, max_children: int = 5) -> str:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        return f"<xml parse error: {e}>"

    lines: list[str] = []
    _render_node(root, lines, depth=0, max_depth=max_depth, max_children=max_children)
    return "\n".join(lines)


def _render_node(
    node: ET.Element,
    lines: list[str],
    depth: int,
    max_depth: int,
    max_children: int,
) -> None:
    indent = "  " * depth
    tag = _strip_ns(node.tag)
    attrs = ""
    if node.attrib:
        attr_parts = [f'{k}="{v}"' for k, v in list(node.attrib.items())[:3]]
        if len(node.attrib) > 3:
            attr_parts.append(f"... +{len(node.attrib) - 3}")
        attrs = " " + " ".join(attr_parts)

    children = list(node)
    text = (node.text or "").strip()

    if not children and not text:
        lines.append(f"{indent}<{tag}{attrs} />")
        return

    if not children:
        preview = text[:60] + ("…" if len(text) > 60 else "")
        lines.append(f"{indent}<{tag}{attrs}> {preview!r}")
        return

    lines.append(f"{indent}<{tag}{attrs}> ({len(children)} children)")

    if depth >= max_depth:
        lines.append(f"{indent}  ...")
        return

    shown = children[:max_children]
    for child in shown:
        _render_node(child, lines, depth + 1, max_depth, max_children)
    if len(children) > max_children:
        lines.append(f"{indent}  ... +{len(children) - max_children} more <{_strip_ns(children[max_children].tag)}>")


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag
