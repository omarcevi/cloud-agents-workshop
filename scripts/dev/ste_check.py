"""Check prose against the measurable ASD-STE100 (Simplified Technical English) rules.

It checks what a script can check without the STE dictionary:
  - sentence length: max 20 words in instructions, max 25 in descriptions
  - paragraph length: max 6 sentences
  - "-ing" forms outside technical names
  - passive voice and perfect tenses (be/have + past participle)
  - modal verbs STE does not use (should, would, could, might, may, shall)
  - contractions
It cannot check that every word is in the STE dictionary with its approved meaning,
or the noun-cluster limit (max 3 words); review those by hand.

Code (fenced blocks, <pre>, <code>, `inline`) is skipped. Usage:
  uv run python scripts/dev/ste_check.py FILE.md|FILE.html ... [--strict]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

# -ing words that are not verb forms, or are part of technical names.
ING_OK = {
    "during",
    "nothing",
    "something",
    "anything",
    "everything",
    "thing",
    "things",
    "string",
    "strings",
    "morning",
    "evening",
    "ceiling",
    "ring",
    "bring",
    "spring",
    "billing",
    "logging",
    "monitoring",
    "tracing",
    "streaming",
    "routing",
    "pricing",
    "setting",
    "settings",
    "meeting",
    "building",
    "learning",
    "computing",
    "networking",
    "staging",
    "encoding",
    "sampling",
    "thinking",
    "grounding",
    "onboarding",
    "testing",
    "rehearsing",
    "ticketing",
    "binding",
    "king",
    "ping",
    "wing",
    "sing",
    "swing",
    "sting",
    "bing",
}
IRREGULAR_PARTICIPLES = {
    "built",
    "sent",
    "made",
    "given",
    "taken",
    "shown",
    "written",
    "kept",
    "held",
    "found",
    "done",
    "seen",
    "told",
    "left",
    "lost",
    "paid",
    "sold",
    "bound",
    "broken",
    "chosen",
    "driven",
    "drawn",
    "fallen",
    "forgotten",
    "frozen",
    "hidden",
    "known",
    "laid",
    "led",
    "meant",
    "met",
    "proven",
    "spent",
    "stolen",
    "thrown",
    "understood",
    "won",
    "worn",
    "withdrawn",
    "begun",
    "brought",
    "bought",
    "caught",
    "taught",
    "thought",
    "got",
    "gotten",
}
IMPERATIVES = {
    "add",
    "allow",
    "apply",
    "ask",
    "bind",
    "book",
    "change",
    "check",
    "choose",
    "click",
    "close",
    "compare",
    "configure",
    "confirm",
    "copy",
    "create",
    "delete",
    "deploy",
    "do",
    "download",
    "edit",
    "enable",
    "find",
    "follow",
    "give",
    "go",
    "grant",
    "install",
    "keep",
    "let",
    "look",
    "make",
    "move",
    "open",
    "paste",
    "pick",
    "point",
    "put",
    "read",
    "remove",
    "replace",
    "run",
    "score",
    "see",
    "select",
    "send",
    "set",
    "start",
    "stop",
    "tell",
    "tick",
    "try",
    "turn",
    "type",
    "use",
    "wait",
    "write",
    "never",
    "always",
    "agree",
    "count",
    "decide",
    "ship",
    "show",
    "teach",
    "treat",
    "ignore",
    "register",
    "record",
}
MODALS = re.compile(r"\b(should|would|could|might|may|shall|ought)\b")
CONTRACTION = re.compile(
    r"\b\w+(n't|'re|'ll|'ve|'m|'d)\b|\b(it|that|there|what|here|let|who)'s\b", re.I
)
BE = r"(am|is|are|was|were|be|been|being)"
HAVE = r"(has|have|had)"


def participle(word: str) -> bool:
    w = word.lower()
    return (w.endswith("ed") and len(w) > 3) or w in IRREGULAR_PARTICIPLES


def blocks_from_markdown(text: str) -> list[tuple[str, str]]:
    """(kind, text) per paragraph or list item; kind is 'list' or 'text'."""
    text = re.sub(r"(?ms)^\s*```.*?^\s*```\s*$", "\n", text)
    out = []
    for raw in re.split(r"\n\s*\n|\n(?=\s*(?:\d+\.|[-*])\s)", text):
        b = raw.strip()
        if not b or b.startswith(("#", "|", "<walkthrough-metadata", "![", "&nbsp;")):
            continue
        kind = "list" if re.match(r"(\d+\.|[-*])\s", b) else "text"
        out.append((kind, b))
    return out


def blocks_from_html(text: str) -> list[tuple[str, str]]:
    text = re.sub(r"(?is)<(pre|script|style|svg)\b.*?</\1>", "\n", text)
    text = re.sub(r"(?is)<div class=\"(code|out)\".*?</div>", "\n", text)
    text = re.sub(r"(?is)<(table)\b.*?</\1>", "\n", text)
    out = []
    for m in re.finditer(
        r"(?is)<(p|li|figcaption|summary|dd|aside)\b[^>]*>(.*?)</\1>", text
    ):
        inner = re.sub(
            r"(?is)<(ul|ol)\b.*", "", m.group(2)
        )  # nested lists are their own blocks
        out.append(("list" if m.group(1).lower() == "li" else "text", inner))
    return out


def clean(fragment: str) -> str:
    s = re.sub(r"(?is)<code\b[^>]*>.*?</code>", " X ", fragment)
    s = re.sub(r"`[^`]*`", " X ", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # markdown links
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"^\s*(\d+\.|[-*])\s+", "", s)
    s = re.sub(r"\*\*|__|\*", "", s)
    return re.sub(r"\s+", " ", s).strip()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", text)
    return [p.strip() for p in parts if re.search(r"[A-Za-z]", p)]


def words(sentence: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][\w'\u2019./:-]*", sentence)


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    blocks = (
        blocks_from_html(text) if path.suffix == ".html" else blocks_from_markdown(text)
    )
    problems = []
    for kind, raw in blocks:
        para = clean(raw)
        if not para:
            continue
        sents = sentences(para)
        if len(sents) > 6:
            problems.append(
                f"paragraph has {len(sents)} sentences (max 6): {para[:90]}…"
            )
        for s in sents:
            w = words(s)
            first = w[0].lower() if w else ""
            instruction = first in IMPERATIVES or (
                kind == "list" and first in IMPERATIVES
            )
            limit = 20 if instruction else 25
            if len(w) > limit:
                problems.append(f"{len(w)} words (max {limit}): {s}")
            for tok in w:
                t = tok.lower().strip(".,:;'\u2019")
                if (
                    t.endswith("ing")
                    and t not in ING_OK
                    and len(t) > 4
                    and not tok[:1].isupper()
                ):
                    problems.append(f'"-ing" form "{tok}": {s}')
            lower = s.lower()
            for m in re.finditer(rf"\b{BE}\s+(not\s+)?(\w+)\b", lower):
                if participle(m.group(3)):
                    problems.append(f'passive or adjective "{m.group(0)}" (check): {s}')
            for m in re.finditer(rf"\b{HAVE}\s+(\w+)\b", lower):
                if participle(m.group(2)):
                    problems.append(f'perfect tense "{m.group(0)}": {s}')
            for m in MODALS.finditer(s):
                problems.append(f'modal "{m.group(0)}": {s}')
            if CONTRACTION.search(s):
                problems.append(f"contraction: {s}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 if anything is flagged"
    )
    args = parser.parse_args()
    total = 0
    for path in args.files:
        problems = check_file(path)
        total += len(problems)
        for p in problems:
            print(f"{path}: {p}")
    print(f"{total} issues in {len(args.files)} files", file=sys.stderr)
    return 1 if args.strict and total else 0


if __name__ == "__main__":
    sys.exit(main())
