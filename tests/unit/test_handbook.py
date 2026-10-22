"""Handbook retrieval: section splitting and retrieval quality on a small fixed query set."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools import handbook

# (query, the section that must be the top hit)
GOLDEN = [
    ("how many unused leave days can I carry over", "01-leave-policy.md#carry-over"),
    ("public holidays istanbul office", "01-leave-policy.md#public-holidays"),
    ("annual leave entitlement Berlin", "01-leave-policy.md#annual-leave-entitlement"),
    ("notice period for requesting leave", "01-leave-policy.md#requesting-leave"),
    ("on-call swap platform team leave", "01-leave-policy.md#platform-team-on-call"),
    ("office anchor days hybrid", "02-remote-work.md#hybrid-schedule"),
    (
        "work from another country abroad",
        "02-remote-work.md#working-from-another-country",
    ),
    ("laptop stolen what priority", "03-it-equipment-and-support.md#laptops"),
    (
        "ticket priority response time P2",
        "03-it-equipment-and-support.md#priorities-and-response-times",
    ),
    ("reset my SSO password", "03-it-equipment-and-support.md#passwords-and-access"),
    ("per diem allowance EU", "04-expenses-and-travel.md#per-diem"),
    (
        "can you tell me my colleague's salary",
        "05-compensation-and-confidentiality.md#individual-compensation-is-confidential",
    ),
    ("when is pay reviewed", "05-compensation-and-confidentiality.md#how-pay-works"),
]


def test_sections_are_split_with_anchors() -> None:
    passages = handbook.split_sections(
        handbook.config.HANDBOOK_DIR / "01-leave-policy.md"
    )
    sources = [p.source for p in passages]
    assert "01-leave-policy.md#carry-over" in sources
    assert all(p.title.startswith("Leave policy: ") for p in passages)


def test_tokenizer_folds_case_and_turkish_diacritics() -> None:
    assert handbook.tokenize("İstanbul Ofisi ŞAHİN colleagues") == [
        "istanbul",
        "ofisi",
        "sahin",
        "colleague",
    ]


@pytest.mark.parametrize(("query", "expected"), GOLDEN)
def test_top_hit(query: str, expected: str) -> None:
    results = handbook.get_index().search(query, top_k=3)
    assert results, query
    assert results[0][0].source == expected, [p.source for p, _ in results]


def test_recall_at_3_on_golden_set() -> None:
    hits = sum(
        expected in [p.source for p, _ in handbook.get_index().search(q, top_k=3)]
        for q, expected in GOLDEN
    )
    assert hits / len(GOLDEN) == 1.0


def test_tool_returns_citable_passages() -> None:
    result = handbook.handbook_search("carry over")
    assert result["passages"][0]["source"] == "01-leave-policy.md#carry-over"
    assert {"source", "title", "text", "score"} <= set(result["passages"][0])


def test_no_match_says_so() -> None:
    result = handbook.handbook_search("zebra quantum")
    assert result["passages"] == [] and "do not guess" in result["note"]


def test_index_on_custom_directory(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Doc\n\n## Pets\n\nDogs are allowed on Fridays.\n")
    index = handbook.BM25Index(list(handbook.split_sections(tmp_path / "a.md")))
    assert index.search("dogs friday")[0][0].source == "a.md#pets"
