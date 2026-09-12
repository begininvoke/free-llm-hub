r"""Freebuff is installed and opened BESIDE the hub, not routed through it.

Asked for: "connect freebuff from the hub ... run in background ... use their
CLI." Freebuff is Codebuff's free coding agent -- a terminal TUI, not an
OpenAI-compatible endpoint. Its free models answer only requests that look
byte-for-byte like its own CLI (system prompt, publisher, one-model session;
see common/src/constants/free-agents.ts), and the upstream 403s a direct call
with "may get your account banned". So the hub does NOT proxy it, strip its
ads, or rotate accounts against its gate -- that would be circumventing its
access control.

What the hub does: install Freebuff into its own isolated npm prefix + HOME,
and open it in its own window in the project folder a Build session is using.
It runs alongside the hub (the hub returns at once, does not block); it needs
its own console because the TUI exits 139 with no terminal, so it is not
pretended to be headless. The ads stay in Freebuff's own window.
"""
import os

import pytest

import app as A


APP = open("app.py", encoding="utf-8").read()
SRC = open("templates/index.html", encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _tok(monkeypatch):
    monkeypatch.setattr(A, "_has_control_token", lambda: True)
    yield


def _hdr():
    return {"X-Free-LLM-Hub": "dashboard",
            "X-Free-LLM-Hub-Token": A.config.get_control_token() or ""}


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #

def test_freebuff_lives_in_its_own_isolated_dirs():
    assert A._freebuff_install_dir().endswith(os.path.join("freebuff", "install"))
    assert A._freebuff_home().endswith(os.path.join("freebuff", "home"))
    assert "isolated-clis" in A._freebuff_root()


def test_its_env_is_a_home_of_its_own_with_no_hub_pointers(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_freebuff_home", lambda: str(tmp_path / "fbhome"))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8787")
    monkeypatch.setattr(A, "_points_at_hub", lambda v: isinstance(v, str) and "127.0.0.1:8787" in v)
    env = A._freebuff_env()
    assert env["HOME"] == str(tmp_path / "fbhome")
    assert env["USERPROFILE"] == str(tmp_path / "fbhome")
    assert "ANTHROPIC_BASE_URL" not in env, "a hub-pointing var must be stripped"


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #

def test_status_reports_not_installed(monkeypatch):
    monkeypatch.setattr(A, "_freebuff_bin", lambda: None)
    r = A.app.test_client().get("/api/freebuff/status", headers=_hdr())
    assert r.status_code == 200
    d = r.get_json()
    assert d["installed"] is False
    assert "not routed through the hub" in d["note"]


def test_status_reports_installed(monkeypatch, tmp_path):
    fake = tmp_path / "freebuff.cmd"
    fake.write_text("x", encoding="utf-8")
    monkeypatch.setattr(A, "_freebuff_bin", lambda: str(fake))
    d = A.app.test_client().get("/api/freebuff/status", headers=_hdr()).get_json()
    assert d["installed"] is True and d["bin_path"]


# --------------------------------------------------------------------------- #
# Open
# --------------------------------------------------------------------------- #

def test_open_refuses_a_folder_that_is_not_there(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_freebuff_bin", lambda: str(tmp_path / "freebuff.cmd"))
    r = A.app.test_client().post("/api/freebuff/open",
                                 json={"project_dir": str(tmp_path / "nope")}, headers=_hdr())
    assert r.status_code == 400


def test_open_needs_it_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_freebuff_bin", lambda: None)
    r = A.app.test_client().post("/api/freebuff/open",
                                 json={"project_dir": str(tmp_path)}, headers=_hdr())
    assert r.status_code == 400 and r.get_json()["code"] == "not_installed"


def test_open_launches_in_its_own_window_and_returns_at_once(monkeypatch, tmp_path):
    fake = tmp_path / "freebuff.cmd"
    fake.write_text("x", encoding="utf-8")
    monkeypatch.setattr(A, "_freebuff_bin", lambda: str(fake))
    monkeypatch.setattr(A, "_freebuff_env", lambda: {"HOME": str(tmp_path)})
    calls = {}

    class _Popen:
        def __init__(self, argv, **kw):
            calls["argv"] = argv
            calls["cwd"] = kw.get("cwd")
            calls["flags"] = kw.get("creationflags")
    monkeypatch.setattr(A.subprocess, "Popen", _Popen)
    if os.name == "nt":
        monkeypatch.setattr(A.subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    r = A.app.test_client().post("/api/freebuff/open",
                                 json={"project_dir": str(tmp_path)}, headers=_hdr())
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert "--cwd" in calls["argv"] and str(tmp_path) in calls["argv"]
    assert calls["cwd"] == str(tmp_path)
    if os.name == "nt":
        # its own console -- never CREATE_NO_WINDOW, which crashes the TUI
        assert calls["flags"] and calls["flags"] & A.subprocess.CREATE_NEW_CONSOLE
        assert calls["flags"] & A._CREATE_NO_WINDOW == 0 or A._CREATE_NO_WINDOW == 0


def test_install_needs_npm(monkeypatch):
    monkeypatch.setattr(A.shutil, "which", lambda n: None)
    r = A.app.test_client().post("/api/freebuff/install", json={}, headers=_hdr())
    assert r.status_code == 400 and "npm" in r.get_json()["error"].lower()


# --------------------------------------------------------------------------- #
# The hub does NOT proxy it
# --------------------------------------------------------------------------- #

def test_freebuff_is_not_a_routed_provider():
    """No /v1 provider, no chain hop, no ad-stripping: only install/open/status."""
    import re
    routes = set(re.findall(r'@app\.route\("(/api/freebuff/[^"]+)"', APP))
    assert routes == {"/api/freebuff/status", "/api/freebuff/models", "/api/freebuff/install", "/api/freebuff/open"}
    # It is not registered as a provider anywhere.
    assert '"freebuff"' not in APP[APP.index("PROVIDERS = "):APP.index("PROVIDERS = ") + 200] \
        if "PROVIDERS = " in APP else True


def test_the_code_says_why_it_is_not_proxied():
    body = APP[APP.index("# Freebuff -- the free Codebuff"):]
    body = body[:body.index("_FREEBUFF_PKG")]
    assert "may get your account banned" in body
    assert "does NOT proxy it, strip its" in body


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #

def test_the_build_page_has_the_button():
    assert 'id="agent-freebuff"' in SRC
    body = SRC[SRC.index("function initAgentFreebuff()"):]
    body = body[:body.index("function initAgentMode()")]
    assert "/api/freebuff/status" in body
    assert "/api/freebuff/install" in body
    assert "/api/freebuff/open" in body
    assert "cxAgentProjectDir" in body
    assert "initAgentFreebuff();" in SRC


# --------------------------------------------------------------------------- #
# The Providers page card
# --------------------------------------------------------------------------- #

def test_the_providers_page_has_a_freebuff_card():
    assert 'id="freebuff-card"' in SRC
    assert 'id="fb-install"' in SRC and 'id="fb-open"' in SRC
    body = SRC[SRC.index("function initFreebuffCard()"):]
    body = body[:body.index("function loadProviders()")]
    assert "/api/freebuff/status" in body
    assert "/api/freebuff/install" in body
    assert "/api/freebuff/open" in body
    assert "/api/agent/new-project" in body, "the card makes a folder to run in"
    assert "initFreebuffCard();" in SRC


def test_the_card_says_it_is_not_a_routed_provider():
    i = SRC.index('id="freebuff-card"')
    around = SRC[i - 400:i + 700]
    assert "not proxied through the hub" in around or "not a routed" in around
    assert "ads stay in" in around


def test_the_card_points_to_the_models_already_routable():
    i = SRC.index('id="freebuff-card"')
    around = SRC[i:i + 1600]
    assert "Its free models, live in the hub" in around
    assert 'id="fb-models"' in around


# --------------------------------------------------------------------------- #
# Dynamic detection of the free models already in the hub
# --------------------------------------------------------------------------- #

def _fake_tracking(monkeypatch, models):
    class _R:
        def get_json(self):
            return {"models": models}
    monkeypatch.setattr(A, "api_tracking", lambda: _R())
    # No network in the test: pin the free families to a known set.
    monkeypatch.setattr(A, "_freebuff_families", lambda: [
        ("glm-5-3-flash", "GLM 5 3 Flash"), ("deepseek-flash", "Deepseek Flash"),
        ("mimo", "Mimo"), ("minimax-m3", "Minimax M3"), ("luna", "Luna")])


def test_it_detects_the_free_models_live(monkeypatch):
    _fake_tracking(monkeypatch, [
        {"model": "z-ai/glm-5.3-flash", "provider": "nvidia", "state": "ok", "score": 9, "id": "nvidia/z-ai/glm-5.3-flash"},
        {"model": "deepseek-ai/DeepSeek-V4.1-Flash", "provider": "dahl", "state": "ok", "score": 8, "id": "dahl/deepseek-ai/DeepSeek-V4.1-Flash"},
        {"model": "mimo-v2.5-pro", "provider": "g4f", "state": "dead", "score": 1, "id": "g4f/mimo-v2.5-pro"},
    ])
    d = A.app.test_client().get("/api/freebuff/models", headers=_hdr()).get_json()
    by = {m["name"]: m for m in d["models"]}
    assert by["GLM 5 3 Flash"]["available"] is True and "nvidia" in by["GLM 5 3 Flash"]["providers"]
    assert by["Deepseek Flash"]["available"] is True, "V4.1 Flash counts as DeepSeek flash"
    assert by["Deepseek Flash"]["pick"] == "dahl/deepseek-ai/DeepSeek-V4.1-Flash"
    assert by["Mimo"]["available"] is False, "a dead hit is not available"
    assert d["available"] >= 2


def test_the_newest_deepseek_v4_1_flash_is_recognised(monkeypatch):
    _fake_tracking(monkeypatch, [
        {"model": "deepseek-v4.1-flash", "provider": "x", "state": "ok", "score": 5, "id": "x/deepseek-v4.1-flash"},
    ])
    d = A.app.test_client().get("/api/freebuff/models", headers=_hdr()).get_json()
    assert next(m for m in d["models"] if m["name"] == "Deepseek Flash")["available"] is True


def test_the_detector_never_500s(monkeypatch):
    def boom():
        raise RuntimeError("no tracking")
    monkeypatch.setattr(A, "api_tracking", boom)
    r = A.app.test_client().get("/api/freebuff/models", headers=_hdr())
    assert r.status_code == 200 and r.get_json()["available"] == 0


def test_the_card_renders_the_live_models():
    body = SRC[SRC.index("function initFreebuffCard()"):]
    body = body[:body.index("function loadProviders()")]
    assert "/api/freebuff/models" in body
    assert 'id="fb-models"' in SRC
    assert "loadModels();" in body


# --------------------------------------------------------------------------- #
# The list is read from Codebuff's repo, not hardcoded
# --------------------------------------------------------------------------- #

FA_SAMPLE = """
  export const FREE_AGENTS = {
    'base2-free-deepseek-flash': X, 'base2-free-deepseek-flash-max': X,
    'base3-free-glm-5-3-flash': X, 'base2-free-mimo': X, 'base2-free-mimo-pro': X,
    'base2-free-luna': X, 'base2-free-luna-es': X, 'base2-free-solar-pro4': X,
    'base2-free-kimi-k3-eco': X, 'base3-free-newmodel-2': X,
  }
"""


def test_families_are_parsed_from_the_repo_text():
    fams = dict(A._freebuff_parse_families(FA_SAMPLE))
    slugs = set(fams)
    assert "deepseek-flash" in slugs
    assert "deepseek-flash-max" not in slugs, "tier suffixes are collapsed"
    assert "glm-5-3-flash" in slugs and "mimo" in slugs and "luna" in slugs
    assert "kimi-k3-eco" in slugs, "a family the old hardcoded list never had"
    assert "newmodel" in slugs, "a brand-new free family shows up with no code change"


def test_patterns_cover_the_dot_and_synonym_forms():
    assert "glm-5.3-flash" in A._freebuff_patterns("glm-5-3-flash")
    assert "luna" in A._freebuff_patterns("luna") and "gpt-5.6" in A._freebuff_patterns("luna")
    assert "solar" in A._freebuff_patterns("solar-pro4")


def test_it_falls_back_to_a_seed_offline(monkeypatch):
    """A failed fetch must not blank the card."""
    class _Boom:
        def __init__(self, *a, **k): raise RuntimeError("offline")
    monkeypatch.setattr(A.requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    with A._freebuff_models_lock:
        A._freebuff_models_cache.update({"at": 0.0, "families": None})
    fams = A._freebuff_families()
    assert fams and len(fams) >= 5, "the seed keeps the card populated when offline"
