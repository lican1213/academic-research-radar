"""One-time state reset for GitHub forks, not for the upstream repository.

The first scan in a fork must not inherit the upstream owner's seen ledger.
Only public research metadata and bootstrap marker are touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

UPSTREAM = "lican1213/academic-research-radar"


def initialize_fork(repository: str, data: Path) -> str:
    if repository == UPSTREAM:
        return "upstream_unchanged"
    if not repository or repository.count("/") != 1 or any(
        not part or part in (".", "..") for part in repository.split("/")
    ):
        raise ValueError("GITHUB_REPOSITORY must be OWNER/REPO")
    marker = data / "fork_initialized.json"
    if marker.exists():
        state = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("repository") != repository:
            raise ValueError("fork_initialized.json belongs to another repository")
        return "already_initialized"
    data.mkdir(parents=True, exist_ok=True)
    for name in ("seen.json", "chinese_seen.json"):
        (data / name).write_text("{}\n", encoding="utf-8")
    (data / "latest.json").write_text(json.dumps({
        "generated_at": None,
        "status": "not_run",
        "reason": "This fork has not completed its first independent scan.",
        "new_candidates": [],
        "chinese_new_candidates": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (data / "latest.md").write_text(
        "# Fork not yet scanned\n\nThe upstream owner's previous research results were cleared.\n",
        encoding="utf-8")
    marker.write_text(json.dumps({
        "repository": repository,
        "upstream": UPSTREAM,
        "version": 1,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "new_fork_initialized"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(initialize_fork(args.repository, args.data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
