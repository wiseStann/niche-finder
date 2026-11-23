"""Run profiles (filtered runs with their own outputs), `nf run` progress events and the `nf ui` server. Offline."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from nichefinder import niches, profiles, ui
from nichefinder.cli import main
from nichefinder.workspace import Workspace, WorkspaceError

NICHES = [dict(n, who="small teams", task="the job", product="SaaS", competitors=["A", "B", "C"]) for n in [
    {"id": "dog-daycare", "name": "Dog daycare software", "geo": "global", "side": "b2b-smb", "tier": "A"},
    {"id": "budget-app", "name": "Budget app", "geo": "both", "side": "b2c", "tier": "B"},
    {"id": "ru-crm", "name": "Russian CRM", "geo": "ru", "side": "b2b-smb", "tier": "A"},
    {"id": "ctrl-notes", "name": "Notes (control)", "geo": "global", "side": "prosumer", "tier": "C"},
]]


def _queries(lang: str, base: str) -> list[dict]:
    return [{"q": f"{base} software", "i": "category", "anchor": True}, {"q": f"{base} app", "i": "category"},
            {"q": f"{base} tool", "i": "category"}, {"q": f"how to {base}", "i": "problem"},
            {"q": f"{base} brand one", "i": "brand", "b": "One"}, {"q": f"{base} brand two", "i": "brand", "b": "Two"}]


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ww", "ru"]}), encoding="utf-8")
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump(NICHES), encoding="utf-8")
    q = {"dog-daycare": {"en": _queries("en", "dog daycare")},
         "budget-app": {"en": _queries("en", "budget"), "ru": _queries("ru", "бюджет")},
         "ru-crm": {"ru": _queries("ru", "црм")},
         "ctrl-notes": {"en": _queries("en", "notes")}}
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump(q, allow_unicode=True), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(
        yaml.safe_dump({"tier_a": [{"id": "dog-daycare"}, {"id": "budget-app"}], "tier_c": [{"id": "ctrl-notes"}]}),
        encoding="utf-8")
    return Workspace(tmp_path)


def test_profile_filters_niches_and_moves_outputs(tmp_path):
    ws = make_ws(tmp_path)
    prof = profiles.create(ws, {"markets": ["us", "ww"], "side": ["b2b-smb"], "tier": ["A", "B", "C"]})
    assert prof.profile == "west-b2b"
    assert prof.markets == ["us", "ww"]
    # ru-crm is B2B but has no English queries, so a western run has nothing to measure for it
    assert [n["id"] for n in niches.load_niches(prof)] == ["dog-daycare"]
    assert niches.shortlist_ids(prof) == ["dog-daycare"]
    assert set(niches.load(prof)[1]) == {"dog-daycare"}
    assert len(niches.load_niches(prof, scoped=False)) == 4
    errors, _, stats = niches.validate(prof)            # validation always covers every niche
    assert not errors and stats["niches"] == 4
    root = tmp_path.resolve()
    assert prof.out("x.csv") == root / "profiles" / "west-b2b" / "data" / "out" / "x.csv"
    assert prof.report("r.md") == root / "profiles" / "west-b2b" / "reports" / "r.md"
    assert prof.raw("a.csv") == root / "data" / "raw" / "a.csv"          # source dumps and cache are shared
    assert prof.cache("itunes") == root / "data" / "cache" / "itunes"
    assert Workspace.find(tmp_path, "west-b2b").profile_spec == prof.profile_spec


def test_profile_spec_normalization_and_names(tmp_path):
    ws = make_ws(tmp_path)
    full = {"markets": ["ru", "us", "ww"], "side": ["b2b-smb", "b2c", "prosumer"], "tier": ["A", "B", "C"]}
    assert profiles.normalize(ws, full) == {}
    assert profiles.create(ws, full).profile is None                    # the full run needs no profile
    assert profiles.auto_name(ws, profiles.normalize(ws, {"markets": ["ru"], "side": ["b2c", "prosumer"]})) == "ru-b2c"
    assert profiles.auto_name(ws, profiles.normalize(ws, {"tier": ["B", "A"]})) == "tier-ab"
    with pytest.raises(ValueError, match="at least one side"):
        profiles.normalize(ws, {"side": []})
    with pytest.raises(ValueError, match="unknown markets"):
        profiles.normalize(ws, {"markets": ["de"]})
    with pytest.raises(WorkspaceError, match="unknown profile"):
        Workspace(tmp_path, profile="nope")
    with pytest.raises(WorkspaceError, match="bad profile name"):
        Workspace(tmp_path, profile="../x")


def test_new_profile_is_seeded_with_its_rows_only(tmp_path):
    ws = make_ws(tmp_path)
    out = ws.out()
    (out / "metrics_quick.csv").write_text("id,score\ndog-daycare,1\nbudget-app,2\nru-crm,3\n", encoding="utf-8")
    (out / "supply_deep.csv").write_text('niche_id,note\ndog-daycare,"a, b"\nbudget-app,x\n', encoding="utf-8")
    (out / "dfs_us.csv").write_text("keyword,search_volume\nbudget app,10\ndog daycare software,20\n", encoding="utf-8")
    (out / "coverage.csv").write_text("entity,niche_id\nAcme,\nPetco,dog-daycare\nMint,budget-app\n", encoding="utf-8")
    (out / "gplay.csv").write_bytes("﻿niche_id,app\ndog-daycare,a\nbudget-app,b\n".encode("utf-8"))
    (out / "docs.jsonl").write_text('{"niche_id": "dog-daycare"}\n{"niche_id": "budget-app"}\n', encoding="utf-8")
    (out / "themes.json").write_text(json.dumps({"dog-daycare": [1], "budget-app": [2]}), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps([{"appId": "x"}]), encoding="utf-8")
    prof = profiles.create(ws, {"side": ["b2b-smb"]})
    p = prof.out()

    def lines(name):
        return p.joinpath(name).read_text(encoding="utf-8-sig").splitlines()
    assert lines("metrics_quick.csv") == ["id,score", "dog-daycare,1", "ru-crm,3"]
    assert lines("supply_deep.csv") == ["niche_id,note", 'dog-daycare,"a, b"']
    assert len(lines("dfs_us.csv")) == 3                     # keyword rows: the incremental state of s3_dataforseo
    assert lines("coverage.csv") == ["entity,niche_id", "Acme,", "Petco,dog-daycare"]
    assert p.joinpath("gplay.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert lines("docs.jsonl") == ['{"niche_id": "dog-daycare"}']
    assert json.loads(p.joinpath("themes.json").read_text(encoding="utf-8")) == {"dog-daycare": [1]}
    assert json.loads(p.joinpath("plan.json").read_text(encoding="utf-8")) == [{"appId": "x"}]
    assert len((out / "metrics_quick.csv").read_text(encoding="utf-8").splitlines()) == 4   # the full run is untouched


def test_run_events_and_keep_going(tmp_path, monkeypatch, capsys):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("NF_EVENTS", "1")
    # s0_merge stops itself (no raw dumps): without -k the run ends there, with -k s1_niches still runs
    with pytest.raises(SystemExit, match="no raw source files"):
        main(["-w", str(ws.root), "run", "s0_merge", "s1_niches"])
    events = [json.loads(line[5:]) for line in capsys.readouterr().out.splitlines() if line.startswith("@@nf ")]
    assert [e["ev"] for e in events] == ["plan", "start", "fail"]
    assert events[0]["stages"] == ["s0_merge", "s1_niches"]
    with pytest.raises(SystemExit) as exit_info:
        main(["-w", str(ws.root), "run", "s0_merge", "s1_niches", "-k"])
    assert exit_info.value.code == 1
    events = [json.loads(line[5:]) for line in capsys.readouterr().out.splitlines() if line.startswith("@@nf ")]
    assert [(e["ev"], e.get("stage")) for e in events] == [
        ("plan", None), ("start", "s0_merge"), ("fail", "s0_merge"), ("start", "s1_niches"), ("done", "s1_niches"),
        ("end", None)]
    assert events[-1]["failed"] == ["s0_merge"]


def test_profile_command_and_run_under_profile(tmp_path, capsys):
    ws = make_ws(tmp_path)
    main(["-w", str(ws.root), "profile", "b2c", "--side", "b2c,prosumer"])
    assert "2 niches in scope" in capsys.readouterr().out
    main(["-w", str(ws.root), "-p", "b2c", "run", "s1_niches"])
    assert (tmp_path / "profiles" / "b2c" / "reports" / "S1-niche-universe.md").is_file()
    assert not (tmp_path / "reports" / "S1-niche-universe.md").exists()
    main(["-w", str(ws.root), "profile"])
    assert "b2c" in capsys.readouterr().out


def test_targets_are_compressed():
    from nichefinder.stages import STAGES
    assert ui.targets_for([s.name for s in STAGES if s.in_all]) == ["all"]
    assert ui.targets_for(["s1_niches", "s1_coverage", "s7_html"]) == ["s1", "s7_html"]


@pytest.fixture
def server(tmp_path):
    ws = make_ws(tmp_path)
    httpd = ui.make_server(ws, port=0)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield httpd, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.app.closing = True
    httpd.app.runner.stop()
    httpd.shutdown()
    httpd.server_close()


def _post(base, path, body, token):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-NF-Token": token})
    return json.load(urllib.request.urlopen(req, timeout=10))


def test_ui_server_guards_and_preview(server):
    httpd, base = server
    token = httpd.app.token
    assert token in urllib.request.urlopen(base + "/", timeout=10).read().decode()
    state = json.load(urllib.request.urlopen(base + "/api/state", timeout=10))
    assert len(state["niches"]) == 4 and state["markets"] == ["us", "ww", "ru"]
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base, "/api/run", {"stages": ["s1_niches"]}, "wrong")
    assert e.value.code == 403
    req = urllib.request.Request(base + "/api/state", headers={"Host": "attacker.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 403
    p = _post(base, "/api/preview", {"spec": {"markets": ["ru"], "side": ["b2b-smb"]}}, token)
    assert (p["profile"], p["niches"]) == ("ru-b2b", 1)
    assert p["ready"]["s2_wordstat"] != "market ru is off in nf.yaml"
    assert any("US demand" in w for w in p["warnings"])
    assert _post(base, "/api/preview", {"spec": {"tier": []}}, token) == {"error": "pick at least one tier"}
    assert httpd.app.report_file("-", "../nf.yaml") is None


def test_ui_server_runs_a_stage_and_streams_its_events(server, tmp_path):
    httpd, base = server
    meta = _post(base, "/api/run", {"spec": {"side": ["b2b-smb"]}, "stages": ["s1_niches"]}, httpd.app.token)
    assert meta["profile"] == "b2b" and meta["targets"] == ["s1_niches"]
    deadline = time.time() + 60
    events: list[dict] = []
    seq = 0
    while time.time() < deadline and not any(e["type"] == "end" for e in events):
        for n, data in httpd.app.runner.since(seq, timeout=1):
            seq = n
            events.append(json.loads(data))
    kinds = [(e["type"], e.get("stage"), e.get("status")) for e in events if e["type"] != "log"]
    assert kinds[:4] == [("run", None, None), ("plan", None, None), ("stage", "s1_niches", "running"),
                         ("stage", "s1_niches", "done")]
    assert events[-1]["status"] == "ok"
    assert any("OK: 2 niches" in e.get("line", "") for e in events)
    res = json.load(urllib.request.urlopen(base + "/api/results?profile=b2b", timeout=10))
    assert [r["name"] for r in res["reports"]] == ["S1-niche-universe.md"]
    md = urllib.request.urlopen(base + "/r/b2b/S1-niche-universe.md", timeout=10).read().decode()
    assert "dog-daycare" in md and "budget-app" not in md
    assert json.load(urllib.request.urlopen(base + "/api/state", timeout=10))["history"][0]["status"] == "ok"
    assert (tmp_path / "logs" / "ui" / "stage_times.json").is_file()
