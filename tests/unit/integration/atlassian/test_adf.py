"""ADF -> text. The output is deliberately markdown-ish rather than
faithful: an LLM reading an issue or a page wants the words, the headings
and the list structure, not the mark spans."""

from app.integration.atlassian.content import adf


def _doc(*content: dict) -> dict:  # type: ignore[type-arg]
    return {"type": "doc", "version": 1, "content": list(content)}


def _paragraph(text: str) -> dict:  # type: ignore[type-arg]
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


class TestRender:
    def test_renders_paragraph_text(self):
        assert adf.render(_doc(_paragraph("Hello."))) == "Hello."

    def test_renders_headings_at_their_level(self):
        document = _doc(
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Background"}],
            }
        )

        assert adf.render(document) == "## Background"

    def test_renders_a_bullet_list(self):
        document = _doc(
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [_paragraph("one")]},
                    {"type": "listItem", "content": [_paragraph("two")]},
                ],
            }
        )

        assert adf.render(document) == "- one\n- two"

    def test_numbers_an_ordered_list(self):
        document = _doc(
            {
                "type": "orderedList",
                "content": [
                    {"type": "listItem", "content": [_paragraph("first")]},
                    {"type": "listItem", "content": [_paragraph("second")]},
                ],
            }
        )

        assert adf.render(document) == "1. first\n2. second"

    def test_renders_a_code_block_with_its_language(self):
        document = _doc(
            {
                "type": "codeBlock",
                "attrs": {"language": "python"},
                "content": [{"type": "text", "text": "x = 1"}],
            }
        )

        assert adf.render(document) == "```python\nx = 1\n```"

    def test_renders_a_mention_as_its_text(self):
        document = _doc(
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "ask "},
                    {"type": "mention", "attrs": {"text": "@Dev User"}},
                ],
            }
        )

        assert adf.render(document) == "ask @Dev User"

    def test_keeps_the_words_of_an_unrecognised_node(self):
        """New ADF node types appear over time. Losing the formatting is
        acceptable; silently losing the content is not."""
        document = _doc(
            {
                "type": "somethingNewAtlassianAdded",
                "content": [_paragraph("still readable")],
            }
        )

        assert adf.render(document) == "still readable"

    def test_renders_nothing_for_a_missing_body(self):
        assert adf.render(None) == ""
        assert adf.render("not a document") == ""
