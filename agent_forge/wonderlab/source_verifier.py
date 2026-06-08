"""Source verification gate for Wonderlab episode artifacts."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime
from html import unescape
from typing import Callable

from .schema import Source


@dataclass(frozen=True)
class FetchedPage:
    url: str
    status_code: int
    content_type: str
    text: str
    content_bytes: bytes = b""


FetchSource = Callable[[Source], FetchedPage]


def verify_sources(
    sources: list[Source],
    fetcher: FetchSource | None = None,
    checked_at: str | None = None,
) -> list[Source]:
    """Verify every source URL and return updated immutable Source objects."""
    now = checked_at or datetime.now().isoformat(timespec="seconds")
    fetch = fetcher or fetch_source_url
    verified: list[Source] = []

    for source in sources:
        if not source.url:
            verified.append(_mark(
                source,
                status="needs-human-review",
                checked_at=now,
                error="No URL is available for automated verification.",
            ))
            continue

        try:
            page = fetch(source)
        except Exception as exc:
            verified.append(_mark(
                source,
                status="fetch-error",
                checked_at=now,
                error=f"{type(exc).__name__}: {str(exc)[:220]}",
            ))
            continue

        if page.status_code == 404:
            verified.append(_mark(
                source,
                status="not-found",
                checked_at=now,
                error="URL returned 404.",
            ))
            continue
        if page.status_code in (401, 403):
            verified.append(_mark(
                source,
                status="access-blocked",
                checked_at=now,
                error=(
                    f"URL returned HTTP {page.status_code}; automated verifier "
                    "could not read it."
                ),
            ))
            continue
        if page.status_code >= 400:
            verified.append(_mark(
                source,
                status="fetch-error",
                checked_at=now,
                error=f"URL returned HTTP {page.status_code}.",
            ))
            continue

        if _looks_like_pdf(source, page):
            pdf_text = _extract_pdf_text(page.content_bytes, fallback=page.text)
            clean_pdf_text = _clean_text(pdf_text)
            if _source_matches_page(source, clean_pdf_text, source.title):
                verified.append(_mark(
                    source,
                    status="verified-pdf",
                    checked_at=now,
                    title=_pdf_title(source),
                    excerpt=_best_excerpt(clean_pdf_text, source),
                ))
            else:
                verified.append(_mark(
                    source,
                    status="needs-human-review",
                    checked_at=now,
                    title=_pdf_title(source),
                    excerpt=(
                        "PDF was reachable, but automated text extraction did not "
                        "clearly match the expected source."
                    ),
                ))
            continue

        clean_text = _clean_text(page.text)
        page_title = _extract_title(page.text)
        if _source_matches_page(source, clean_text, page_title):
            verified.append(_mark(
                source,
                status="verified",
                checked_at=now,
                title=page_title,
                excerpt=_best_excerpt(clean_text, source),
            ))
        else:
            verified.append(_mark(
                source,
                status="reachable-title-mismatch",
                checked_at=now,
                title=page_title,
                excerpt=_best_excerpt(clean_text, source),
                error="Fetched page did not clearly contain the expected source title or publisher.",
            ))

    return verified


def fetch_source_url(source: Source, timeout: int = 15) -> FetchedPage:
    """Fetch a source URL with a plain stdlib client."""
    request = urllib.request.Request(
        source.url,
        headers={
            "User-Agent": (
                "WonderlabSourceVerifier/0.1 "
                "(structured citation verification; contact: local)"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1_250_000)
            content_type = response.headers.get("content-type", "")
            encoding = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(encoding, errors="replace")
            return FetchedPage(
                url=response.geturl(),
                status_code=getattr(response, "status", 200),
                content_type=content_type,
                text=text,
                content_bytes=raw,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        return FetchedPage(
            url=source.url,
            status_code=exc.code,
            content_type=exc.headers.get("content-type", ""),
            text=body,
            content_bytes=body.encode("utf-8", errors="replace"),
        )


def summarize_source_verification(sources: list[Source]) -> str:
    """Return a compact summary for the run stage."""
    counts: dict[str, int] = {}
    for source in sources:
        counts[source.verification_status] = counts.get(source.verification_status, 0) + 1
    parts = [f"{count} {status}" for status, count in sorted(counts.items())]
    return ", ".join(parts) if parts else "no sources"


def _mark(
    source: Source,
    *,
    status: str,
    checked_at: str,
    title: str = "",
    excerpt: str = "",
    error: str = "",
) -> Source:
    return replace(
        source,
        verification_status=status,
        verified_title=title[:240],
        verification_excerpt=excerpt[:420],
        verification_error=error[:320],
        checked_at=checked_at,
    )


def _looks_like_pdf(source: Source, page: FetchedPage) -> bool:
    return (
        source.url.lower().endswith(".pdf")
        or "application/pdf" in page.content_type.lower()
        or page.text.startswith("%PDF")
    )


def _pdf_title(source: Source) -> str:
    return source.title if source.title else "Reachable PDF"


def _extract_pdf_text(raw: bytes, fallback: str = "") -> str:
    """Best-effort text extraction for simple PDFs without external deps."""
    if not raw:
        return fallback

    decoded = raw.decode("latin-1", errors="ignore")
    strings: list[str] = []
    for match in re.finditer(r"\((?:\\.|[^\\()]){3,}\)", decoded):
        value = match.group(0)[1:-1]
        value = value.replace(r"\(", "(").replace(r"\)", ")")
        value = value.replace(r"\n", " ").replace(r"\r", " ")
        value = value.replace(r"\t", " ")
        strings.append(value)

    text = " ".join(strings)
    if len(text.strip()) < 80:
        text = fallback or decoded
    return text


def _extract_title(raw: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
    if not match:
        return ""
    return _clean_text(match.group(1))[:240]


def _source_matches_page(source: Source, clean_text: str, page_title: str) -> bool:
    haystack = f"{page_title} {clean_text}".lower()
    title_terms = _meaningful_terms(source.title)
    publisher_terms = _meaningful_terms(source.publisher)

    if title_terms:
        title_hits = sum(1 for term in title_terms if term in haystack)
        required = max(1, min(len(title_terms), 2))
        if title_hits >= required:
            return True

    if publisher_terms:
        publisher_hits = sum(1 for term in publisher_terms if term in haystack)
        if publisher_hits >= max(1, min(len(publisher_terms), 2)):
            return True

    return False


def _best_excerpt(clean_text: str, source: Source) -> str:
    terms = _meaningful_terms(source.title) + _meaningful_terms(source.publisher)
    lowered = clean_text.lower()
    indexes = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = min(indexes) if indexes else 0
    start = max(0, start - 80)
    excerpt = clean_text[start:start + 360].strip()
    return excerpt or clean_text[:360].strip()


def _meaningful_terms(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop = {
        "a",
        "an",
        "and",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
    }
    return [word for word in words if len(word) > 2 and word not in stop]


def _clean_text(raw: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
