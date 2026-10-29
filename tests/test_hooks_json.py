"""hooks.json is valid, and the startup check warns loudly when python3 is missing."""
import json
import subprocess
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "plugins" / "devflow" / "hooks" / "hooks.json"


def startup_command():
    data = json.loads(HOOKS.read_text())
    entry = next(e for e in data["hooks"]["SessionStart"] if "startup" in e["matcher"])
    return entry["hooks"][0]["command"]


def test_every_script_in_hooks_json_exists():
    data = json.loads(HOOKS.read_text())
    for groups in data["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                if "scripts/" in hook["command"]:
                    name = hook["command"].split("scripts/")[1].rstrip('"')
                    assert (HOOKS.parent.parent / "scripts" / name).is_file(), name


def test_startup_check_silent_with_python():
    out = subprocess.run(["bash", "-c", startup_command()], capture_output=True, text=True)
    assert out.stdout == "" and out.returncode == 0


def test_startup_check_warns_without_python():
    out = subprocess.run(["/bin/bash", "-c", startup_command()], capture_output=True, text=True,
                         env={"PATH": "/nonexistent"})
    assert "NOT active" in json.loads(out.stdout)["systemMessage"]
