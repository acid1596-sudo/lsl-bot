import json

import pytest

from lslbot.tasks import GENERAL, TASKS, TaskSettings, automatic_model, get_task, is_model_name

INSTALLED = [
    {"name": "llama3:latest", "size": 4_700_000_000},
    {"name": "qwen2.5-coder:7b", "size": 4_700_000_000},
    {"name": "qwen3-coder:30b", "size": 18_600_000_000},
    {"name": "gpt-oss:20b", "size": 13_800_000_000},
]


def test_the_tasks_on_offer():
    assert [t.id for t in TASKS] == ["general", "mesh", "lsl", "code"]
    assert get_task("mesh").label == "Mesh for Second Life"
    assert get_task("nope") is None and get_task(None) is None and get_task(["mesh"]) is None
    assert GENERAL.instructions == ""


def test_code_tasks_pick_the_biggest_coding_model_installed():
    for task_id in ("mesh", "lsl", "code"):
        assert automatic_model(get_task(task_id), "llama3", INSTALLED) == "qwen3-coder:30b"


def test_general_keeps_the_usual_model():
    assert automatic_model(GENERAL, "llama3", INSTALLED) == "llama3"


def test_without_a_coding_model_code_tasks_use_the_usual_model():
    assert automatic_model(get_task("mesh"), "llama3", [{"name": "llama3:latest", "size": 1}]) == "llama3"
    assert automatic_model(get_task("mesh"), "llama3", None) == "llama3"
    assert automatic_model(get_task("mesh"), "llama3", []) == "llama3"


def test_task_instructions_ask_for_complete_work():
    mesh = get_task("mesh").instructions
    assert "ONE complete Blender Python script" in mesh
    assert "export_scene.gltf" in mesh and "Build > Upload > Model..." in mesh
    assert "complete script" in get_task("lsl").instructions
    assert "complete files" in get_task("code").instructions


@pytest.mark.parametrize(
    "name", ["llama3", "qwen3-coder:30b", "hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q4_K_M", "continue-local:9b-64k"]
)
def test_ollama_model_names(name):
    assert is_model_name(name)


@pytest.mark.parametrize("name", ["", " llama3", "llama3; rm -rf", "../llama3", "a" * 201, None, 3])
def test_things_that_are_not_model_names(name):
    assert not is_model_name(name)


def test_picked_models_are_saved_and_come_back(tmp_path):
    path = tmp_path / "data" / "tasks.json"
    settings = TaskSettings(str(path))
    assert settings.chosen_model("mesh") == ""

    settings.choose_model("mesh", "qwen3-coder:30b")
    assert TaskSettings(str(path)).chosen_model("mesh") == "qwen3-coder:30b"

    settings.choose_model("mesh", "")
    assert TaskSettings(str(path)).chosen_model("mesh") == ""
    assert sorted(p.name for p in path.parent.iterdir()) == ["tasks.json"]


def test_a_damaged_settings_file_is_ignored(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text("{not json")
    assert TaskSettings(str(path)).chosen_model("mesh") == ""

    path.write_text(json.dumps({"models": {"mesh": "qwen3-coder:30b", "nope": "llama3", "lsl": "bad name!"}}))
    settings = TaskSettings(str(path))
    assert settings.chosen_model("mesh") == "qwen3-coder:30b"
    assert settings.chosen_model("nope") == "" and settings.chosen_model("lsl") == ""


def test_settings_without_a_file_live_in_memory():
    settings = TaskSettings(None)
    settings.choose_model("code", "qwen3-coder:30b")
    assert settings.chosen_model("code") == "qwen3-coder:30b"
