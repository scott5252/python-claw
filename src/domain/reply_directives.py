from __future__ import annotations

import re
from dataclasses import dataclass, field


DIRECTIVE_PATTERN = re.compile(r"\[\[(reply|media|voice):([^\]]+)\]\]")
ANY_DIRECTIVE_PATTERN = re.compile(r"\[\[[^\]]+\]\]")


@dataclass(frozen=True)
class ParsedReplyDirectives:
    cleaned_text: str
    reply_to_external_id: str | None = None
    media_refs: list[str] = field(default_factory=list)
    voice_media_ref: str | None = None


class ReplyDirectiveError(ValueError):
    pass


def parse_reply_directives(text: str) -> ParsedReplyDirectives:
    reply_to_external_id: str | None = None
    media_refs: list[str] = []
    voice_media_ref: str | None = None

    def replace(match: re.Match[str]) -> str:
        nonlocal reply_to_external_id, voice_media_ref
        directive = match.group(1)
        value = match.group(2).strip()
        if not value:
            raise ReplyDirectiveError("directive value must be non-empty")
        if directive == "reply":
            reply_to_external_id = value
        elif directive == "media":
            media_refs.append(value)
        elif directive == "voice":
            voice_media_ref = value
        return ""

    cleaned_text = DIRECTIVE_PATTERN.sub(replace, text)
    leftover = ANY_DIRECTIVE_PATTERN.search(cleaned_text)
    if leftover is not None:
        raise ReplyDirectiveError("unsupported or malformed directive")
    normalized_text = "\n\n".join(part.strip() for part in cleaned_text.split("\n\n") if part.strip())
    return ParsedReplyDirectives(
        cleaned_text=normalized_text.strip(),
        reply_to_external_id=reply_to_external_id,
        media_refs=media_refs,
        voice_media_ref=voice_media_ref,
    )
