from agent_forge.bus import extract_mentions, extract_requests


def test_extract_requests_supports_spaces_in_name() -> None:
    text = "Please help. [REQUEST @Data Analyst: Validate this CAGR.]"
    assert extract_requests(text) == [("Data Analyst", "Validate this CAGR.")]


def test_extract_requests_allows_multiple_blocks() -> None:
    text = (
        "[REQUEST @Risk-Lead: Check downside.] "
        "[REQUEST @Data Analyst: Recompute with new assumptions.]"
    )
    assert extract_requests(text) == [
        ("Risk-Lead", "Check downside."),
        ("Data Analyst", "Recompute with new assumptions."),
    ]


def test_extract_mentions_supports_underscore_aliases() -> None:
    valid = ["Data Analyst", "Risk-Lead"]
    text = "@Data_Analyst please verify; @Risk-Lead can you challenge assumptions?"
    assert extract_mentions(text, valid) == ["Data Analyst", "Risk-Lead"]
