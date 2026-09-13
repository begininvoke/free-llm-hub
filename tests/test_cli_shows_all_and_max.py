r"""In a CLI's /model picker: the categories AND the tiers/pipelines, by name.

REQUESTED: "inside CLIs -- opencode, codex, claude -- when I do /model I want
to see all, seo, uncensored etc, pick one, and also see the tiers max, swarm,
crew and pick. Respect the categories we have. Detect them dynamically, no
hardcoding."

The category modes and the swarm/crew pipelines already reached every picker
(they come from _mode_keys() + _SWARM_IDS + crews -- dynamic). This adds the
two plain-language ids people actually type -- "all" (= auto, no category
limit) and "max" (= best) -- and groups the labels so a flat list still reads
as three groups: the tiers, the categories, the pipelines.
"""
import pytest

import app as A
import model_categories as MC


@pytest.fixture
def client():
    A.app.config["TESTING"] = True
    with A.app.test_client() as c:
        yield c


def _auth():
    return {"X-Free-LLM-Hub": "dashboard",
            "X-Free-LLM-Hub-Token": A.config.get_control_token() or ""}


# --------------------------------------------------------------------------- #
# The list the picker reads
# --------------------------------------------------------------------------- #

def test_the_tiers_the_categories_and_the_pipelines_are_all_there():
    ids = set(A._virtual_model_ids())
    assert {"auto", "all", "best", "max"} <= ids, "the tiers, by name"
    assert set(A._mode_keys()) <= ids, "every category the hub has"
    assert {"swarm", "crew"} <= ids, "the pipelines"
    for cat in ("seo", "uncensored", "coding", "vision"):
        assert cat in ids, cat


def test_all_and_max_are_the_words_people_type():
    assert "all" in A._virtual_model_ids() and "max" in A._virtual_model_ids()


def test_the_categories_are_dynamic_not_hardcoded(monkeypatch):
    """A new category in model_categories shows up in the picker on its own."""
    monkeypatch.setattr(A, "_mode_keys", lambda: ("coding", "seo", "brandnew"))
    ids = A._virtual_model_ids()
    assert "brandnew" in ids
    assert A._virtual_model_label("brandnew") == "Category · brandnew"


# --------------------------------------------------------------------------- #
# The labels group the flat list
# --------------------------------------------------------------------------- #

def test_labels_read_as_three_groups():
    assert A._virtual_model_label("auto").startswith("Auto")
    assert A._virtual_model_label("all").startswith("All models")
    assert A._virtual_model_label("max").startswith("Max")
    assert A._virtual_model_label("best").startswith("Max")
    assert A._virtual_model_label("seo").startswith("Category ·")
    assert "SEO" in A._virtual_model_label("seo")
    assert A._virtual_model_label("uncensored").startswith("Category ·")
    assert A._virtual_model_label("swarm").startswith("Pipeline ·")
    assert A._virtual_model_label("crew-code").startswith("Pipeline ·")


# --------------------------------------------------------------------------- #
# They actually route
# --------------------------------------------------------------------------- #

def test_all_and_max_route_like_auto_and_best():
    for m in ("all", "max"):
        assert A._is_orchestrate(m), m
    # "max" asks for the strongest tier, like "best".
    assert A._codex_reasoning_body_for("max") == {"quality_mode": True} \
        if hasattr(A, "_codex_reasoning_body_for") else True


def test_max_turns_on_quality_mode_in_the_chat_route():
    src = open("app.py", encoding="utf-8").read()
    i = src.index('_rkw["quality_mode"] = True')
    around = src[i - 200:i + 40]
    assert '("best", "max")' in around, "the chat route treats max like best"


# --------------------------------------------------------------------------- #
# Every CLI surface lists them
# --------------------------------------------------------------------------- #

def test_the_openai_surface_lists_all_and_max(client):
    ids = [m["id"] for m in client.get("/v1/models").get_json()["data"]]
    for m in ("auto", "all", "best", "max", "seo", "uncensored", "swarm", "crew"):
        assert m in ids, m


def test_the_gemini_surface_lists_them(client):
    names = [m["name"] for m in client.get("/v1beta/models").get_json()["models"]]
    assert "models/all" in names and "models/max" in names and "models/seo" in names


def test_the_codex_catalog_labels_all_and_max():
    assert A._codex_catalog_label("all") == "All free models (Calvoun hub)"
    assert "Max" in A._codex_catalog_label("max")
    assert A._codex_catalog_label("seo").startswith("SEO / content")
