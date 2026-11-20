"""Core tests: workspace, keys, HTTP cache, niches validation, stage registry. Offline."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest
import yaml

from nichefinder import http, keys, niches
from nichefinder.cli import main
from nichefinder.stages import STAGES, resolve
from nichefinder.workspace import Workspace, WorkspaceError


def make_ws(tmp_path: Path, settings: dict | None = None) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump(settings or {"markets": ["us"]}), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "dog-daycare", "name": "Dog daycare software", "geo": "global", "side": "b2b-smb", "tier": "A"},
    ]), encoding="utf-8")
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({"dog-daycare": {"en": [
        {"q": "dog daycare software", "i": "category", "anchor": True},
        {"q": "pet boarding software", "i": "category"},
        {"q": "kennel software", "i": "category"},
        {"q": "how to run a dog daycare", "i": "problem"},
        {"q": "gingr", "i": "brand", "b": "Gingr"},
        {"q": "petexec", "i": "brand", "b": "PetExec"},
    ]}}), encoding="utf-8")
    return Workspace(tmp_path)


def test_workspace_paths_and_settings(tmp_path):
    ws = make_ws(tmp_path, {"markets": ["us", "ru"], "as_of": "2026-09-17", "goal": {"net_month_low": 1000}})
    assert ws.markets == ["us", "ru"]
    assert ws.today == dt.date(2026, 9, 17)
    assert ws.setting("goal.net_month_low") == 1000
    assert ws.setting("goal.missing", 5) == 5
    assert ws.out("x.csv") == tmp_path.resolve() / "data" / "out" / "x.csv"
    assert ws.cache("itunes").is_dir()
    assert ws.load_config("absent.yaml", {}) == {}
    with pytest.raises(WorkspaceError):
        ws.load_config("absent.yaml")


def test_workspace_find_walks_up(tmp_path, monkeypatch):
    make_ws(tmp_path)
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    monkeypatch.delenv("NF_WORKSPACE", raising=False)
    assert Workspace.find().root == tmp_path.resolve()


def test_dotenv_does_not_override(tmp_path, monkeypatch):
    monkeypatch.setenv("NF_TEST_A", "from-env")
    monkeypatch.delenv("NF_TEST_B", raising=False)
    (tmp_path / ".env").write_text("NF_TEST_A=from-file\nNF_TEST_B='quoted'\n# comment\n", encoding="utf-8")
    keys.load_dotenv(tmp_path / ".env")
    assert os.environ["NF_TEST_A"] == "from-env"
    assert os.environ["NF_TEST_B"] == "quoted"
    monkeypatch.delenv("NF_TEST_B")


def test_require_missing_key_message(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    with pytest.raises(keys.MissingKey) as e:
        keys.require("DATAFORSEO_LOGIN", purpose="S3")
    assert "dataforseo.com" in str(e.value)


def test_http_cache_hit_needs_no_network(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(http, "request", lambda *a, **k: calls.append(a) or http.Response(200, json.dumps({"ok": 1})))
    url = "https://example.com/api?q=1"
    assert http.get_json(url, cache=tmp_path) == {"ok": 1}
    assert http.get_json(url, cache=tmp_path) == {"ok": 1}
    assert len(calls) == 1
    assert http.cache_file(tmp_path, url).is_file()


def test_http_min_size_skips_block_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(http, "request", lambda *a, **k: http.Response(200, "blocked"))
    http.get_text("https://example.com/", cache=tmp_path, min_size=100)
    assert not any(tmp_path.iterdir())


def test_validate_example_workspace(tmp_path):
    ws = make_ws(tmp_path)
    errors, warns, stats = niches.validate(ws)
    assert errors == []
    assert stats["en"] == 6


def test_validate_catches_missing_anchor(tmp_path):
    ws = make_ws(tmp_path)
    q = yaml.safe_load((tmp_path / "queries" / "q.yaml").read_text(encoding="utf-8"))
    q["dog-daycare"]["en"][0].pop("anchor")
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump(q), encoding="utf-8")
    errors, _, _ = niches.validate(ws)
    assert any("anchors" in e for e in errors)


def test_validate_warns_only_on_shared_demand_queries(tmp_path):
    """A brand shared by two niches is a shared competitor; a shared category query double-counts demand."""
    ws = make_ws(tmp_path)
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "dog-daycare", "geo": "global", "side": "b2b-smb", "tier": "A"},
        {"id": "pet-grooming", "geo": "global", "side": "b2b-smb", "tier": "A"},
    ]), encoding="utf-8")
    q = yaml.safe_load((tmp_path / "queries" / "q.yaml").read_text(encoding="utf-8"))
    q["pet-grooming"] = {"en": [
        {"q": "grooming software", "i": "category", "anchor": True},
        {"q": "kennel software", "i": "category"},       # also a category query of dog-daycare
        {"q": "gingr", "i": "brand", "b": "Gingr"},      # also a brand query of dog-daycare
    ]}
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump(q), encoding="utf-8")
    errors, warns, _ = niches.validate(ws)
    assert errors == []
    dups = [w for w in warns if w.startswith("duplicate query")]
    assert len(dups) == 1 and "'kennel software'" in dups[0]


def test_auto_shortlist_carries_unsettled_controls():
    from nichefinder.stages.s3_report import auto_shortlist

    def row(nid, control="", passed=True, score="60"):
        return {"id": nid, "control": control, "expertise_flag": "0", "us_quick_score": score,
                "us_pass": "1" if passed else "0", "us_gates": "" if passed else "G2:top1",
                "us_demand_cat": "5000", "us_top1_brand_share": "0.6", "us_trend": "FLAT"}

    rows = [row("niche-a"),
            row("ctrl-red-passed", "red"), row("ctrl-red-cut", "red", passed=False),
            row("ctrl-platform-passed", "platform"),
            row("ctrl-green-cut", "green", passed=False), row("ctrl-green-passed", "green"),
            row("ctrl-no-data", "red", score="")]
    sl = auto_shortlist(rows, {"shortlist": {}}, "us")
    assert [it["id"] for it in sl["tier_a"]] == ["niche-a"]
    assert [it["id"] for it in sl["tier_c"]] == ["ctrl-red-passed", "ctrl-platform-passed", "ctrl-green-cut", "ctrl-green-passed"]
    assert "overrides.yaml" in sl["tier_c"][1]["why"]


def test_registry_resolve():
    names = [s.name for s in STAGES]
    assert len(names) == len(set(names))
    assert [s.name for s in resolve(["s3"])] == ["s3_dataforseo", "s3_metrics", "s3_report"]
    assert all(s.in_all for s in resolve(["all"]))
    with pytest.raises(SystemExit):
        resolve(["nope"])


def test_bundled_example_validates(tmp_path):
    """`nf init` copies a workspace that passes `nf validate`."""
    target = tmp_path / "ws"
    main(["init", str(target)])
    assert (target / "nf.yaml").is_file()
    if not (target / "niches.yaml").is_file():
        pytest.skip("example niche catalog not bundled yet")
    errors, _, _ = niches.validate(Workspace(target))
    assert errors == []


def test_urlopen_retries_with_certifi_only_on_certificate_errors(monkeypatch):
    import ssl
    import urllib.error
    import urllib.request
    calls = []

    class Opener:
        def __init__(self, handlers):
            self.handlers = handlers

        def open(self, req, timeout):
            calls.append([type(h).__name__ for h in self.handlers])
            if len(calls) == 1:
                raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get issuer certificate"))
            return "response"

    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: Opener(h))
    monkeypatch.setattr(http, "_certifi_context", lambda: ssl.create_default_context())
    assert http.urlopen(urllib.request.Request("https://example.com"), timeout=5) == "response"
    assert calls == [[], ["HTTPSHandler"]]

    calls.clear()

    class Refusing(Opener):
        def open(self, req, timeout):
            calls.append(1)
            raise urllib.error.URLError(ConnectionRefusedError())

    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: Refusing(h))
    with pytest.raises(urllib.error.URLError):
        http.urlopen(urllib.request.Request("https://example.com"), timeout=5)
    assert calls == [1]                                   # not a certificate problem: no second attempt
