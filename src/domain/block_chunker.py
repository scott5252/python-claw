from __future__ import annotations


def chunk_text(*, text: str, max_text_chars: int) -> list[str]:
    if max_text_chars <= 0:
        raise ValueError("max_text_chars must be positive")
    stripped = text.strip()
    if not stripped:
        return []

    paragraphs = [part.strip() for part in stripped.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_text_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(paragraph, max_text_chars))
            continue
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_text_chars:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _hard_split(text: str, max_text_chars: int) -> list[str]:
    return [text[index:index + max_text_chars] for index in range(0, len(text), max_text_chars) if text[index:index + max_text_chars]]
