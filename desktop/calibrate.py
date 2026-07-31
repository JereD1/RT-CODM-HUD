"""
Calibration tool for HealthCapture's detection thresholds/templates.

Problem this solves: config.py's thresholds and assets/dead.png,alive.png,
lowhp*.png were copied verbatim from the Electron version, never
re-measured against this app's actual mss-based capture. Real captures
show two separate real-data violations:
  - dead frames landing BELOW DEAD_LUM_MIN (pixel_votes never reaches 3)
  - dead_sim AND alive_sim both matching the same dead frame (NCC gate
    fails because the templates don't discriminate)
This script records real, manually-labeled frames so those two things
can be diagnosed from data instead of guessed.

Two ways to record samples now:
  1. From the CLI, given a saved region in LAYOUTS_FILE:
       python calibrate.py capture --team 0 --player 0 --label dead
  2. From the main app itself — press the Alive/Low/Dead button on a
     player's row whenever its shown status is wrong. Both paths call
     the same log_sample() below, so `summarize` sees everything either
     way.

    python calibrate.py summarize
"""
import argparse
import json

import mss

from config import LAYOUTS_FILE, APP_DIR
from analysis import Templates, analyse_frame
from capture import grab_region

CALIBRATION_LOG = APP_DIR / "calibration_log.jsonl"


def log_sample(team: int, player: int, label: str, signal: dict) -> dict:
    """Appends one labeled sample to CALIBRATION_LOG. Shared by both the
    CLI `capture` command and the main app's Alive/Low/Dead buttons, so
    `summarize` sees samples from either source the same way."""
    if label not in ("dead", "alive", "low"):
        raise ValueError("label must be one of: dead, alive, low")

    record = {"team": team, "player": player, "label": label, **signal}
    with open(CALIBRATION_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def _load_region(team: int, player: int) -> dict:
    if not LAYOUTS_FILE.exists():
        raise SystemExit(f"No layout found at {LAYOUTS_FILE} — set up regions in the app first.")
    data = json.loads(LAYOUTS_FILE.read_text())
    key = f"{team}-{player}"
    if key not in data:
        raise SystemExit(f"No saved region for team={team} player={player}. "
                          f"Available: {sorted(data.keys())}")
    return data[key]


def capture_sample(team: int, player: int, label: str):
    """CLI entry point — loads the saved region from disk, grabs+analyses
    a fresh frame, and logs it via log_sample()."""
    if label not in ("dead", "alive", "low"):
        raise SystemExit("--label must be one of: dead, alive, low")

    region = _load_region(team, player)
    sct = mss.mss()
    templates = Templates()

    rgb = grab_region(sct, region)
    signal = analyse_frame(rgb, templates)
    record = log_sample(team, player, label, signal)

    print(f"Recorded [{label}] team={team} player={player}: "
          f"b={record['brightness']:.1f} d={record['dead_sim']:.2f} "
          f"a={record['alive_sim']:.2f} v={record['pixel_votes']} "
          f"low_health={record['low_health']}")
    print(f"→ {CALIBRATION_LOG}")


def summarize():
    if not CALIBRATION_LOG.exists():
        raise SystemExit(f"No calibration data yet at {CALIBRATION_LOG} — run `capture` first.")

    records = [json.loads(line) for line in CALIBRATION_LOG.read_text().splitlines() if line.strip()]
    if not records:
        raise SystemExit("Calibration log is empty.")

    by_label: dict[str, list[dict]] = {}
    for r in records:
        by_label.setdefault(r["label"], []).append(r)

    print(f"{len(records)} samples across {len(by_label)} label(s)\n")

    for label, group in sorted(by_label.items()):
        print(f"=== {label} (n={len(group)}) ===")
        for field in ("brightness", "dead_sim", "alive_sim", "pixel_votes"):
            vals = [r[field] for r in group]
            print(f"  {field:12s} min={min(vals):.2f}  max={max(vals):.2f}  "
                  f"mean={sum(vals)/len(vals):.2f}")
        print()

    if "dead" in by_label and "alive" in by_label:
        dead_b = [r["brightness"] for r in by_label["dead"]]
        alive_b = [r["brightness"] for r in by_label["alive"]]
        dead_d = [r["dead_sim"] for r in by_label["dead"]]
        alive_a_on_dead = [r["alive_sim"] for r in by_label["dead"]]

        print("=== separation check ===")
        print(f"  dead brightness range:  {min(dead_b):.1f} – {max(dead_b):.1f}")
        print(f"  alive brightness range: {min(alive_b):.1f} – {max(alive_b):.1f}")
        if max(dead_b) >= min(alive_b):
            print("  ⚠ brightness ranges OVERLAP — DEAD_LUM_MIN/MAX can't cleanly separate these")
        print(f"  dead_sim on dead frames:  {min(dead_d):.2f} – {max(dead_d):.2f}")
        print(f"  alive_sim on dead frames: {min(alive_a_on_dead):.2f} – {max(alive_a_on_dead):.2f}")
        if max(alive_a_on_dead) >= 0.58:
            print("  ⚠ alive template is ALSO matching dead frames — "
                  "templates don't discriminate, this is the NCC-gate failure")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="Record one labeled sample from a saved region")
    cap.add_argument("--team", type=int, required=True)
    cap.add_argument("--player", type=int, required=True)
    cap.add_argument("--label", required=True, choices=["dead", "alive", "low"])

    sub.add_parser("summarize", help="Print stats and separation check across recorded samples")

    args = parser.parse_args()
    if args.command == "capture":
        capture_sample(args.team, args.player, args.label)
    elif args.command == "summarize":
        summarize()