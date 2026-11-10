from geocoach import clues, config


def test_cached_clues_falls_back_to_cache_on_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for name in ("PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    assert clues.cached_clues(lambda cc: [{"title": "a"}], "FR") == [{"title": "a"}]

    def boom(cc):
        raise RuntimeError("offline")

    assert clues.cached_clues(boom, "fr") == [{"title": "a"}]
    assert clues.cached_clues(boom, "de") == []


def test_format_clues():
    out = clues.format_clues([{"type": "poles", "title": "T", "description": "D", "regions": []}])
    assert out == ["poles: T. D"]
