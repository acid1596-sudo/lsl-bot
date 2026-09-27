import json
import os
import re
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

_MESH_INSTRUCTIONS = """\
You are building a 3D mesh for Second Life. Deliver it as ONE complete Blender Python script that builds the whole object from an empty scene and saves it as a .glb file - never a partial script, placeholders, or parts left for the user to finish. If the object is complicated, simplify the shapes, but still build all of it.

The script must:
- Run in Blender 4.2 or later (including 5.x) and import only bpy, bmesh, math, mathutils, random and pathlib.
- Start by deleting everything in the scene.
- Use real-world size in metres with Z up, and keep every object between 0.01 m and 64 m on each side (Second Life's limits). Put each object's origin at the centre of its base.
- Stay light, because Second Life charges land impact for detail: as few faces as the shape needs (aim for under 5,000 triangles for furniture-sized objects), no hidden or duplicate faces, and normals facing outwards.
- Give each part a named material (Wood, Metal, Glass...), at most 8 per object, and UV-unwrap every mesh so textures can be applied in Second Life.
- Join the parts into one object, unless they should be separate prims of a linkset.
- Apply all transforms, then export with bpy.ops.export_scene.gltf(filepath=str(pathlib.Path.home() / "<object name>.glb"), export_format='GLB', export_apply=True) and print where the file was saved.

After the script, say in a few short lines how to use it: in Blender, open the Scripting tab, click New, paste the script and click Run Script. Then in the Second Life viewer choose Build > Upload > Model..., pick the .glb from your home folder, let the viewer generate the lower levels of detail, choose a simple physics shape, click Calculate Weights and Fee, then Upload."""

_LSL_INSTRUCTIONS = """\
You write LSL (Linden Scripting Language) scripts for Second Life. Always give the complete script, ready to paste into a new script in an object: every state, event and helper function in full - no "..." and no placeholders.
- Use only real LSL functions, events and constants. If something can't be done in LSL, say so plainly and give the closest thing that works.
- Scripts run in Mono with 64 KB of memory: keep lists small, avoid fast timers, and remove listeners you no longer need.
- Say which prim the script goes in (the root or a child), and anything to set up first (notecards, other scripts, permissions).
- After the script, explain in a few lines how to test it in-world."""

_CODE_INSTRUCTIONS = """\
You are a senior software engineer. When you write or change code, give complete files that run as they are - no fragments, placeholders or "rest unchanged" comments. Say where each file goes and exactly how to run it; on Windows, give the PowerShell commands from start to finish. Keep explanations short and put them after the code."""


@dataclass(frozen=True)
class Task:
    """A kind of work. Its instructions go to whichever provider answers, so
    a task keeps its rules when it moves between ChatGPT, Claude and Ollama;
    ``wants_code_model`` makes Ollama pick a coding model for it."""

    id: str
    label: str
    description: str
    instructions: str = ""
    wants_code_model: bool = False


GENERAL = Task("general", "General", "Questions, writing and everything else.")
TASKS: Sequence[Task] = (
    GENERAL,
    Task(
        "mesh",
        "Mesh for Second Life",
        "Builds the object as a Blender script that saves a .glb file to upload in Second Life.",
        _MESH_INSTRUCTIONS,
        wants_code_model=True,
    ),
    Task("lsl", "LSL script", "Complete scripts for objects in Second Life.", _LSL_INSTRUCTIONS, wants_code_model=True),
    Task("code", "Code", "Complete programs and scripts for your PC.", _CODE_INSTRUCTIONS, wants_code_model=True),
)
_BY_ID: Dict[str, Task] = {task.id: task for task in TASKS}

# Names of Ollama's coding models: qwen3-coder, qwen2.5-coder, deepseek-coder,
# codellama, codegemma, starcoder2, devstral...
_CODE_MODEL_HINTS = ("code", "devstral")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")


def get_task(task_id) -> Optional[Task]:
    return _BY_ID.get(task_id) if isinstance(task_id, str) else None


def is_model_name(value) -> bool:
    return isinstance(value, str) and bool(_MODEL_NAME.match(value))


def automatic_model(task: Task, default_model: str, installed: Optional[List[dict]]) -> str:
    """The Ollama model a task uses until someone picks one: the biggest
    coding model installed for code tasks, otherwise OLLAMA_MODEL."""
    if task.wants_code_model and installed:
        coders = [m for m in installed if any(hint in m["name"].lower() for hint in _CODE_MODEL_HINTS)]
        if coders:
            return max(coders, key=lambda m: m.get("size") or 0)["name"]
    return default_model


class TaskSettings:
    """The Ollama model picked for each task on the chat page, saved in a
    small JSON file. A task with no pick uses its automatic model."""

    def __init__(self, path: Optional[str]):
        self._path = path
        self._lock = threading.Lock()
        self._models: Dict[str, str] = {}
        self._load()

    def chosen_model(self, task_id: str) -> str:
        with self._lock:
            return self._models.get(task_id, "")

    def choose_model(self, task_id: str, model: str) -> None:
        """An empty ``model`` goes back to the automatic pick."""
        with self._lock:
            if model:
                self._models[task_id] = model
            else:
                self._models.pop(task_id, None)
            self._save()

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                models = json.load(f).get("models") or {}
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return
        if isinstance(models, dict):
            self._models = {k: v for k, v in models.items() if get_task(k) and is_model_name(v)}

    def _save(self) -> None:
        if not self._path:
            return
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{self._path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"models": self._models}, f, indent=2)
        os.replace(tmp_path, self._path)
