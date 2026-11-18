"""Dataset symbol discovery must not expose auxiliary mark-price files."""

from pathlib import Path

from gridtrade.api.service import ResearchService


class _Live:
    node_url = ""


def test_mark_files_are_not_listed_as_symbols(tmp_path: Path) -> None:
    for name in ("GOOGLUSDT", "GOOGLUSDT_mark", "AMGNUSDT", "AMGNUSDT_mark"):
        (tmp_path / f"{name}_1m.parquet").write_bytes(b"placeholder")
    service = ResearchService(tmp_path, _Live())
    assert service.symbols() == ["AMGNUSDT", "GOOGLUSDT"]
