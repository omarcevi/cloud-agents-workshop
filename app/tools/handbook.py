"""In-process retrieval over the HR handbook (data/handbook/*.md).

BM25 over `##` sections. Six short markdown files don't need a vector database, and
an in-process index keeps lab setup fast. The README describes the upgrade path to
RAG Engine or Vertex AI Search.
"""

from __future__ import annotations

import functools
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app import config

_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its "
    "me my of on or our so than that the their them there this to up was we what "
    "when where which who will with you your".split()
)


@dataclass(frozen=True)
class Passage:
    source: str  # file name and section anchor, for example 01-leave-policy.md#carry-over
    title: str
    text: str


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _stem(word: str) -> str:
    """Fold simple English plurals so "colleagues" matches "colleague"."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return [_stem(w) for w in words if w not in _STOPWORDS]


def _anchor(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize(title)).strip("-")


def split_sections(path: Path) -> list[Passage]:
    """Split one markdown file into passages at `##` headings (the `#` title is kept as context)."""
    doc_title = ""
    passages: list[Passage] = []
    title, lines = "", []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if title and body:
            passages.append(
                Passage(
                    source=f"{path.name}#{_anchor(title)}",
                    title=f"{doc_title}: {title}",
                    text=body,
                )
            )

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            doc_title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            title, lines = line[3:].strip(), []
        else:
            lines.append(line)
    flush()
    return passages


class BM25Index:
    """Okapi BM25 (k1=1.5, b=0.75) over a fixed list of passages."""

    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75):
        self.passages = passages
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(f"{p.title} {p.text}")) for p in passages]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_length = sum(self.lengths) / max(len(self.lengths), 1)
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, top_k: int = 3) -> list[tuple[Passage, float]]:
        terms = tokenize(query)
        scored = []
        for passage, doc, length in zip(self.passages, self.docs, self.lengths, strict=True):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * length / self.avg_length)
                    score += self.idf[term] * tf * (self.k1 + 1) / norm
            if score > 0:
                scored.append((passage, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


@functools.cache
def get_index(handbook_dir: Path = config.HANDBOOK_DIR) -> BM25Index:
    passages = [p for f in sorted(handbook_dir.glob("*.md")) for p in split_sections(f)]
    return BM25Index(passages)


def handbook_search(query: str) -> dict:
    """Search the Kuzey Labs employee handbook (leave, holidays, remote work, IT, expenses, pay policy).

    Args:
        query: What to look up, in a few keywords. For example "carry over unused leave".

    Returns:
        The best matching handbook passages. Cite their `source` in your answer.
    """
    results = get_index().search(query, top_k=3)
    if not results:
        return {"passages": [], "note": "Nothing in the handbook matches. Say so; do not guess."}
    return {
        "passages": [
            {"source": p.source, "title": p.title, "text": p.text, "score": round(s, 2)}
            for p, s in results
        ]
    }
