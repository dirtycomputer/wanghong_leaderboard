"""Lightweight corpus retrieval used by the RAG / agentic baselines.

This is deliberately simple — a keyword-overlap score over the MinerU
markdown files plus the manifest's title and authors. It exists to
demonstrate that *some* retrieval is happening and to give baselines
real arXiv ids to cite; smarter retrieval is left to participant
harnesses.
"""

from __future__ import annotations

import dataclasses
import re
from collections import Counter
from pathlib import Path
from typing import Any

import orjson

_STOPWORDS = {
    "the", "a", "an", "of", "in", "for", "on", "to", "and", "or", "with",
    "by", "from", "is", "are", "was", "were", "be", "been", "as", "at",
    "this", "that", "these", "those", "we", "show", "prove", "proof",
    "paper", "result", "results",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]{2,}")


@dataclasses.dataclass(frozen=True)
class CorpusEntry:
    arxiv_id: str
    version: str
    title: str
    authors: tuple[str, ...]
    markdown_path: Path

    @property
    def id_with_version(self) -> str:
        return f"{self.arxiv_id}{self.version}"


def load_corpus_manifest(corpus_root: Path) -> list[CorpusEntry]:
    """Load ``manifest.jsonl`` and return one :class:`CorpusEntry` per line."""
    manifest = corpus_root / "manifest.jsonl"
    if not manifest.exists():
        return []
    entries: list[CorpusEntry] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = orjson.loads(line)
        except orjson.JSONDecodeError:
            continue
        md_path = Path(obj.get("markdown_path", ""))
        entries.append(
            CorpusEntry(
                arxiv_id=obj.get("arxiv_id", ""),
                version=obj.get("version", ""),
                title=obj.get("title", ""),
                authors=tuple(obj.get("authors") or ()),
                markdown_path=md_path,
            )
        )
    return entries


def retrieve_relevant_papers(
    query: str,
    entries: list[CorpusEntry],
    *,
    top_k: int = 5,
    max_excerpt_chars: int = 1500,
) -> list[dict[str, Any]]:
    """Return the top-k papers by keyword overlap, with short excerpts.

    Each returned dict has ``arxiv_id``, ``title``, ``authors``,
    ``score`` (raw overlap), and ``excerpt`` (first
    ``max_excerpt_chars`` of the MinerU markdown).
    """
    query_tokens = _tokenise(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, CorpusEntry, str]] = []
    for entry in entries:
        title_score = _score_tokens(query_tokens, entry.title)
        excerpt = _read_excerpt(entry.markdown_path, max_excerpt_chars)
        body_score = _score_tokens(query_tokens, excerpt)
        score = body_score + 2.0 * title_score
        if score > 0:
            scored.append((score, entry, excerpt))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[dict[str, Any]] = []
    for score, entry, excerpt in scored[:top_k]:
        out.append(
            {
                "arxiv_id": entry.arxiv_id,
                "version": entry.version,
                "title": entry.title,
                "authors": list(entry.authors),
                "score": float(score),
                "excerpt": excerpt,
            }
        )
    return out


def _tokenise(text: str) -> Counter[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    return Counter(t for t in tokens if t not in _STOPWORDS)


def _score_tokens(query_tokens: Counter[str], text: str) -> float:
    body = _tokenise(text)
    if not body:
        return 0.0
    score = 0.0
    for term, q in query_tokens.items():
        if term in body:
            score += min(q, body[term])
    return score


def _read_excerpt(path: Path, max_chars: int) -> str:
    if not path or not Path(path).exists():
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars]
    return text
