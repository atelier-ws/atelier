from __future__ import annotations

from atelier.infra.code_intel.zoekt.client import ZoektClient


class _FakeZoektServer:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raw_search(self, _query: object) -> object:
        return self.payload


def test_search_treats_null_result_payloads_as_no_hits() -> None:
    client = ZoektClient(_FakeZoektServer({"Result": None}))  # type: ignore[arg-type]

    assert client.search("never-exists") == []


def test_search_treats_null_files_as_no_hits() -> None:
    client = ZoektClient(_FakeZoektServer({"Result": {"Files": None}}))  # type: ignore[arg-type]

    assert client.search("never-exists") == []


def test_search_treats_null_line_matches_as_no_hits() -> None:
    client = ZoektClient(
        _FakeZoektServer(
            {
                "Result": {
                    "Files": [
                        {
                            "FileName": "src/example.py",
                            "LineMatches": None,
                        }
                    ]
                }
            }
        )
    )

    assert client.search("never-exists") == []


def test_search_treats_null_line_fragments_as_single_whole_line_match() -> None:
    client = ZoektClient(
        _FakeZoektServer(
            {
                "Result": {
                    "Files": [
                        {
                            "FileName": "src/example.py",
                            "LineMatches": [
                                {
                                    "LineNumber": 12,
                                    "LineStart": 3,
                                    "LineEnd": 9,
                                    "Line": "cHJpbnQoJ29rJyk=",
                                    "LineFragments": None,
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )

    results = client.search("print")

    assert len(results) == 1
    assert results[0].path == "src/example.py"
    assert len(results[0].matches) == 1
    assert results[0].matches[0].byte_start == 3
    assert results[0].matches[0].byte_end == 9
    assert results[0].matches[0].line_number == 12
    assert results[0].matches[0].line_text == "print('ok')"
