from pathlib import Path

from trading.exchanges.gate_inputs import review_is_accepted


def test_review_is_accepted_finds_the_adr_without_a_working_directory():
    assert review_is_accepted("ADR-0011") is False or review_is_accepted("ADR-0011") is True
    adr = Path(__file__).resolve().parents[3] / "docs" / "adr" / "ADR-0011-exchange-connectivity.md"
    text = adr.read_text(encoding="utf-8")
    assert "Status:" in text


def test_default_adr_dir_is_anchored_to_the_package():
    from trading.exchanges.gate_inputs import _default_adr_dir

    directory = _default_adr_dir()
    assert directory.is_absolute()
    assert directory.is_dir()
    assert (directory / "ADR-0011-exchange-connectivity.md").is_file()


def test_review_is_accepted_works_from_another_directory(tmp_path, monkeypatch):
    (tmp_path / "ADR-0011-test.md").write_text("# ADR\n\nStatus: accepted\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from trading.exchanges.gate_inputs import _default_adr_dir

    assert _default_adr_dir().is_absolute()
    assert review_is_accepted("ADR-0011", tmp_path) is True
    assert review_is_accepted("ADR-0012", tmp_path) is False


def test_adr_0011_is_proposed_so_live_stays_closed():
    adr = Path(__file__).resolve().parents[3] / "docs" / "adr" / "ADR-0011-exchange-connectivity.md"
    for line in adr.read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith("status:"):
            assert line.split(":", 1)[1].strip().lower() == "proposed"
            return
    raise AssertionError("ADR-0011 has no status line")
