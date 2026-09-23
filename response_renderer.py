from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineQueryResultArticle,
    InputRichBlockMathematicalExpression,
    InputRichBlockParagraph,
    InputRichBlockPreformatted,
    InputRichMessage,
    InputRichMessageContent,
    InputTextMessageContent,
    Message,
    RichTextBold,
    RichTextCode,
    RichTextMathematicalExpression,
)


RichTextPart = str | RichTextBold | RichTextCode | RichTextMathematicalExpression | list[Any]


@dataclass(slots=True)
class RenderedResponse:
    rich_message: InputRichMessage
    fallback_text: str


@dataclass(slots=True)
class _Delimiter:
    kind: str
    start: int
    end: int


class _InlineHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[RichTextPart] = []
        self.stack: list[tuple[str, list[RichTextPart]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "br":
            self._append("\n")
            return
        if normalized in {"b", "strong", "code"}:
            self.stack.append((normalized, []))

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized not in {"b", "strong", "code"}:
            return

        for index in range(len(self.stack) - 1, -1, -1):
            stacked_tag, children = self.stack[index]
            if stacked_tag == normalized or {stacked_tag, normalized} <= {"b", "strong"}:
                del self.stack[index:]
                node: RichTextPart
                if stacked_tag in {"b", "strong"}:
                    node = RichTextBold(text=_compact_rich_text(children))
                else:
                    node = RichTextCode(text=_rich_text_plain_text(children))
                self._append(node)
                return

    def handle_data(self, data: str) -> None:
        self._append(data)

    def handle_entityref(self, name: str) -> None:
        self._append(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self._append(html.unescape(f"&#{name};"))

    def close_open_tags(self) -> None:
        while self.stack:
            tag, children = self.stack.pop()
            if tag in {"b", "strong"}:
                self._append(RichTextBold(text=_compact_rich_text(children)))
            elif tag == "code":
                self._append(RichTextCode(text=_rich_text_plain_text(children)))

    def _append(self, value: RichTextPart) -> None:
        if isinstance(value, str) and value == "":
            return
        target = self.stack[-1][1] if self.stack else self.parts
        if isinstance(value, str) and target and isinstance(target[-1], str):
            target[-1] += value
        else:
            target.append(value)


def _compact_rich_text(parts: list[RichTextPart]) -> str | list[RichTextPart]:
    if len(parts) == 1:
        return parts[0]
    return parts


def _rich_text_plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_rich_text_plain_text(item) for item in value)
    if isinstance(value, RichTextMathematicalExpression):
        return value.expression
    text = getattr(value, "text", None)
    if text is not None:
        return _rich_text_plain_text(text)
    return ""


def _parse_html_inline(text: str) -> list[RichTextPart]:
    parser = _InlineHTMLParser()
    parser.feed(text)
    parser.close_open_tags()
    return parser.parts


def _append_rich_text(parts: list[RichTextPart], value: RichTextPart) -> None:
    if isinstance(value, str) and value == "":
        return
    if isinstance(value, str) and parts and isinstance(parts[-1], str):
        parts[-1] += value
    else:
        parts.append(value)


def _find_unescaped(text: str, needle: str, start: int = 0) -> int:
    position = text.find(needle, start)
    while position != -1:
        backslashes = 0
        cursor = position - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return position
        position = text.find(needle, position + len(needle))
    return -1


def _parse_inline(text: str) -> str | list[RichTextPart]:
    parts: list[RichTextPart] = []
    index = 0

    while index < len(text):
        lower_text = text.lower()
        candidates = [
            position
            for position in (
                _find_unescaped(text, r"\(", index),
                _find_unescaped(text, "`", index),
                _find_unescaped(text, "**", index),
                _find_unescaped(text, "__", index),
                lower_text.find("<b>", index),
                lower_text.find("<strong>", index),
                lower_text.find("<code>", index),
            )
            if position != -1
        ]
        if not candidates:
            for part in _parse_html_inline(text[index:]):
                _append_rich_text(parts, part)
            break

        position = min(candidates)
        for part in _parse_html_inline(text[index:position]):
            _append_rich_text(parts, part)

        if text.startswith(r"\(", position):
            closing = _find_unescaped(text, r"\)", position + 2)
            if closing == -1:
                _append_rich_text(parts, text[position : position + 2])
                index = position + 2
                continue
            expression = text[position + 2 : closing].strip()
            if expression:
                _append_rich_text(parts, RichTextMathematicalExpression(expression=expression))
            index = closing + 2
            continue

        if text.startswith("`", position):
            closing = _find_unescaped(text, "`", position + 1)
            if closing == -1:
                _append_rich_text(parts, "`")
                index = position + 1
                continue
            _append_rich_text(parts, RichTextCode(text=text[position + 1 : closing]))
            index = closing + 1
            continue

        marker = "**" if text.startswith("**", position) else "__" if text.startswith("__", position) else ""
        if marker:
            closing = _find_unescaped(text, marker, position + 2)
            if closing == -1:
                _append_rich_text(parts, marker)
                index = position + 2
                continue
            _append_rich_text(parts, RichTextBold(text=_parse_inline(text[position + 2 : closing])))
            index = closing + 2
            continue

        for tag, closing_tag in (
            ("<strong>", "</strong>"),
            ("<code>", "</code>"),
            ("<b>", "</b>"),
        ):
            if lower_text.startswith(tag, position):
                closing = lower_text.find(closing_tag, position + len(tag))
                if closing == -1:
                    for part in _parse_html_inline(text[position : position + len(tag)]):
                        _append_rich_text(parts, part)
                    index = position + len(tag)
                    break
                content = html.unescape(text[position + len(tag) : closing])
                if tag == "<code>":
                    _append_rich_text(parts, RichTextCode(text=content))
                else:
                    _append_rich_text(parts, RichTextBold(text=_parse_inline(content)))
                index = closing + len(closing_tag)
                break

    return _compact_rich_text(parts)


def _plain_fallback(text: str) -> str:
    cleaned = re.sub(r"```([A-Za-z0-9_+.-]*)\n?", "", text)
    cleaned = cleaned.replace("```", "")
    cleaned = re.sub(r"<tg-math-block>(.*?)</tg-math-block>", r"$$\1$$", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"</?(?:b|strong|code|pre)(?:\s+[^>]*)?>", "", cleaned, flags=re.I)
    return html.unescape(cleaned).replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n").strip()


def _find_next_delimiter(text: str, start: int) -> _Delimiter | None:
    delimiters = [
        ("code", _find_unescaped(text, "```", start), 3),
        ("math_dollar", _find_unescaped(text, "$$", start), 2),
        ("math_square", _find_unescaped(text, r"\[", start), 2),
    ]

    lower_text = text.lower()
    pre_position = lower_text.find("<pre", start)
    math_tag_position = lower_text.find("<tg-math-block>", start)
    if pre_position != -1:
        tag_end = text.find(">", pre_position)
        if tag_end != -1:
            delimiters.append(("html_pre", pre_position, tag_end - pre_position + 1))
    if math_tag_position != -1:
        delimiters.append(("html_math", math_tag_position, len("<tg-math-block>")))

    found = [(kind, position, length) for kind, position, length in delimiters if position != -1]
    if not found:
        return None

    kind, position, length = min(found, key=lambda item: item[1])
    return _Delimiter(kind=kind, start=position, end=position + length)


def _extract_code_block(text: str, delimiter: _Delimiter) -> tuple[str | None, str, int]:
    line_end = text.find("\n", delimiter.end)
    if line_end == -1:
        line_end = delimiter.end
    language = text[delimiter.end:line_end].strip() or None
    body_start = line_end + 1 if line_end < len(text) and text[line_end] == "\n" else line_end
    closing = _find_unescaped(text, "```", body_start)
    if closing == -1:
        return language, text[body_start:], len(text)
    return language, text[body_start:closing], closing + 3


def _extract_html_pre(text: str, delimiter: _Delimiter) -> tuple[str | None, str, int]:
    closing = text.lower().find("</pre>", delimiter.end)
    if closing == -1:
        return None, text[delimiter.start:], len(text)

    content = text[delimiter.end:closing]
    language = None
    code_match = re.search(
        r"<code(?:\s+class=[\"']language-([^\"']+)[\"'])?>(.*?)</code>",
        content,
        flags=re.I | re.S,
    )
    if code_match:
        language = code_match.group(1)
        content = code_match.group(2)
    return language, html.unescape(content), closing + len("</pre>")


def _extract_math_block(text: str, delimiter: _Delimiter) -> tuple[str, int]:
    if delimiter.kind == "math_dollar":
        closing = _find_unescaped(text, "$$", delimiter.end)
        if closing == -1:
            return text[delimiter.start:], len(text)
        return text[delimiter.end:closing].strip(), closing + 2

    if delimiter.kind == "math_square":
        closing = _find_unescaped(text, r"\]", delimiter.end)
        if closing == -1:
            return text[delimiter.start:], len(text)
        return text[delimiter.end:closing].strip(), closing + 2

    closing = text.lower().find("</tg-math-block>", delimiter.end)
    if closing == -1:
        return text[delimiter.start:], len(text)
    return text[delimiter.end:closing].strip(), closing + len("</tg-math-block>")


def _append_paragraphs(blocks: list[Any], text: str) -> None:
    normalized = text.strip("\n")
    if not normalized.strip():
        return

    for paragraph in re.split(r"\n{2,}", normalized):
        if paragraph.strip():
            blocks.append(InputRichBlockParagraph(text=_parse_inline(paragraph.strip("\n"))))


def render_response(text: str) -> RenderedResponse:
    blocks: list[Any] = []
    index = 0

    while index < len(text):
        delimiter = _find_next_delimiter(text, index)
        if not delimiter:
            _append_paragraphs(blocks, text[index:])
            break

        _append_paragraphs(blocks, text[index:delimiter.start])

        if delimiter.kind == "code":
            language, code_text, index = _extract_code_block(text, delimiter)
            blocks.append(InputRichBlockPreformatted(text=code_text.rstrip("\n"), language=language))
            continue

        if delimiter.kind == "html_pre":
            language, code_text, index = _extract_html_pre(text, delimiter)
            blocks.append(InputRichBlockPreformatted(text=code_text.rstrip("\n"), language=language))
            continue

        expression, index = _extract_math_block(text, delimiter)
        if expression:
            blocks.append(InputRichBlockMathematicalExpression(expression=expression))

    if not blocks:
        blocks.append(InputRichBlockParagraph(text=text or " "))

    return RenderedResponse(
        rich_message=InputRichMessage(blocks=blocks),
        fallback_text=_plain_fallback(text) or "Не получил текстовый ответ от модели.",
    )


def build_guest_rich_result(rendered: RenderedResponse, result_id: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=result_id,
        title="Ответ",
        input_message_content=InputRichMessageContent(rich_message=rendered.rich_message),
    )


def build_guest_text_result(rendered: RenderedResponse, result_id: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=result_id,
        title="Ответ",
        input_message_content=InputTextMessageContent(message_text=rendered.fallback_text, parse_mode=None),
    )


async def send_response(message: Message, rendered: RenderedResponse) -> None:
    try:
        await message.bot.send_rich_message(
            chat_id=message.chat.id,
            rich_message=rendered.rich_message,
            message_thread_id=message.message_thread_id or None,
        )
    except TelegramBadRequest:
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=rendered.fallback_text,
            message_thread_id=message.message_thread_id or None,
        )


async def answer_guest_response(message: Message, rendered: RenderedResponse, result_id: str) -> None:
    if not message.guest_query_id:
        return

    try:
        await message.bot.answer_guest_query(
            guest_query_id=message.guest_query_id,
            result=build_guest_rich_result(rendered, result_id),
        )
    except TelegramBadRequest:
        await message.bot.answer_guest_query(
            guest_query_id=message.guest_query_id,
            result=build_guest_text_result(rendered, result_id),
        )
