"""Local control panel for the HR-Agent's behaviour.

A second, independent app: it reads and writes config/rules.json --
the same file the decision layer (decision/engine.py) reads on every
classification call -- so edits made here take effect on the agent's
next run without restarting anything. This app never imports the Gmail
connector or the Claude client, and main.py never imports this app;
either can run without the other.

Run with:
    python webapp/app.py
then open http://127.0.0.1:5151/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, redirect, render_template, request, url_for

from config.rules import DAY_NAMES, INTERVAL_CHOICES_MINUTES, load_rules, save_rules

app = Flask(__name__)

INTERVAL_LABELS = {
    0: "Every trigger (10 min, default)",
    15: "Every 15 minutes",
    30: "Every 30 minutes",
    60: "Every hour",
    120: "Every 2 hours",
    240: "Every 4 hours",
}


def _mappings_to_text(mappings: dict) -> str:
    lines = [f"{category} = {path}" for category, path in mappings.items() if category != "default"]
    return "\n".join(lines)


def _text_to_mappings(text: str) -> dict:
    mappings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        category, path = line.split("=", 1)
        category, path = category.strip(), path.strip()
        if category and path:
            mappings[category] = path
    return mappings


@app.route("/", methods=["GET"])
def index():
    rules = load_rules()
    folder_mappings = rules.get("folder_mappings", {})
    schedule = rules.get("schedule", {})
    return render_template(
        "index.html",
        orchestrator_prompt=rules.get("orchestrator_prompt", ""),
        sub_agents=rules.get("sub_agents", []),
        default_folder=folder_mappings.get("default", ""),
        extra_mappings_text=_mappings_to_text(folder_mappings),
        schedule_enabled=schedule.get("enabled", False),
        schedule_days=[
            (
                day,
                schedule.get("windows", {}).get(day, ""),
                schedule.get("intervals", {}).get(day, 0),
            )
            for day in DAY_NAMES
        ],
        interval_choices=[(minutes, INTERVAL_LABELS[minutes]) for minutes in INTERVAL_CHOICES_MINUTES],
        saved=request.args.get("saved") == "1",
    )


@app.route("/save", methods=["POST"])
def save():
    rules = load_rules()

    rules["orchestrator_prompt"] = request.form.get("orchestrator_prompt", "").strip()

    indices = sorted(
        {key[len("subagent_name_"):] for key in request.form if key.startswith("subagent_name_")},
        key=int,
    )
    sub_agents = []
    for idx in indices:
        name = request.form.get(f"subagent_name_{idx}", "").strip()
        if not name:
            continue
        sub_agents.append(
            {
                "name": name,
                "description": request.form.get(f"subagent_description_{idx}", "").strip(),
                "prompt": request.form.get(f"subagent_prompt_{idx}", "").strip(),
            }
        )
    rules["sub_agents"] = sub_agents

    default_folder = request.form.get("default_folder", "").strip()
    folder_mappings = _text_to_mappings(request.form.get("extra_mappings", ""))
    folder_mappings["default"] = default_folder or rules["folder_mappings"].get("default", "")
    rules["folder_mappings"] = folder_mappings

    intervals = {}
    for day in DAY_NAMES:
        try:
            intervals[day] = int(request.form.get(f"schedule_interval_{day}", "0") or 0)
        except ValueError:
            intervals[day] = 0

    rules["schedule"] = {
        "enabled": request.form.get("schedule_enabled") == "on",
        "windows": {day: request.form.get(f"schedule_{day}", "").strip() for day in DAY_NAMES},
        "intervals": intervals,
    }

    save_rules(rules)
    return redirect(url_for("index", saved="1"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5151, debug=True)
