"""Atlassian Document Format -> plain text.

ADF is the body format for Jira descriptions and comments, and Confluence
serves the same shape when asked for ``atlas_doc_format``, so one renderer
covers both. The output is deliberately markdown-ish rather than faithful:
an LLM reading an issue wants the words, the headings and the list structure,
not the mark spans.
"""

from typing import Any

_BULLET = "- "
_MAX_HEADING_LEVEL = 6


def render(node: Any) -> str:
    """Render an ADF document (or any ADF node) to text. Anything that is not
    a recognised node renders as its plain text content, so an unknown node
    type loses its formatting but never its words."""
    if not isinstance(node, dict):
        return ""

    return _render_node(node, depth=0).strip()


def _render_node(node: dict[str, Any], depth: int) -> str:
    node_type = node.get("type")

    if node_type == "text":
        text: str = node.get("text", "")
        return text

    if node_type == "hardBreak":
        return "\n"

    if node_type == "heading":
        level = min(int(node.get("attrs", {}).get("level", 1)), _MAX_HEADING_LEVEL)
        return f"{'#' * level} {_render_children(node, depth, '')}\n"

    if node_type in {"bulletList", "orderedList"}:
        return _render_list(node, depth)

    if node_type == "codeBlock":
        language = node.get("attrs", {}).get("language", "")
        return f"```{language}\n{_render_children(node, depth, '')}\n```\n"

    if node_type == "blockquote":
        inner = _render_children(node, depth, "\n").strip()
        quoted = "\n".join(f"> {line}" for line in inner.splitlines())
        return f"{quoted}\n"

    if node_type == "rule":
        return "---\n"

    if node_type in {"mention", "emoji"}:
        attrs = node.get("attrs", {})
        return str(attrs.get("text") or attrs.get("shortName") or "")

    if node_type == "paragraph":
        return f"{_render_children(node, depth, '')}\n"

    # doc, table rows/cells, panels, and anything unrecognised: keep the words.
    return _render_children(node, depth, "\n")


def _render_list(node: dict[str, Any], depth: int) -> str:
    ordered = node.get("type") == "orderedList"
    indent = "  " * depth
    lines = []

    for index, item in enumerate(node.get("content", []), start=1):
        marker = f"{index}. " if ordered else _BULLET
        body = _render_node(item, depth + 1).strip()
        if not body:
            continue
        first, *rest = body.splitlines()
        lines.append(f"{indent}{marker}{first}")
        lines.extend(f"{indent}  {line}" for line in rest)

    return "\n".join(lines) + "\n"


def _render_children(node: dict[str, Any], depth: int, separator: str) -> str:
    return separator.join(
        _render_node(child, depth)
        for child in node.get("content", [])
        if isinstance(child, dict)
    )
