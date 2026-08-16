#!/usr/bin/env python3
"""Check that openspec changes spanning several repos still agree with each other.

A change that spans repos is recorded twice by design: a **root** holds the plan
and lists its sub-changes, and each **sub-change** lives in the repo whose files
it edits and points back at the root. Two records of one plan is exactly the
shape that drifts, and cross-repo links are plain prose — nothing in `openspec
validate` can see past its own repo.

So this walks the links in both directions and reports what has come apart.
Everything it checks has already happened here at least once.

  COPY        the same change exists in another repo with no Part of: line —
              not a sub-change, a duplicate. jgt-appliance carried five of
              these, inherited when the repo was generated, and one of them
              still said the off-site upload was "unverified for want of R2
              credentials" a day after it was proven impossible. An agent
              opening that repo would have re-derived the whole finding.
  DANGLING    a sub-change names a root that does not exist
  MISSING     a root lists a sub-change that does not exist
  PREMATURE   a root was archived while one of its sub-changes is still active
  UNDECLARED  an active change with no `**Owning repo**` line, so nobody knows
              which agent owns it. Only demanded of repos that opted in, by
              carrying the rule in their own openspec/config.yaml — a
              single-repo project has nothing to route and should not be nagged.
              COPY and the link checks apply everywhere, because a dangling
              reference is wrong regardless of whose convention it is.

Usage:  ./scripts/check-change-orchestration.py [repos-dir]
        repos-dir defaults to the parent of this repository.

Exit 0 when every link resolves, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

OWNER_RE = re.compile(r"\*\*Owning repo\*\*[：:]\s*`?([A-Za-z0-9._/-]+)`?")
PART_OF_RE = re.compile(r"Part of[：:]\s*`?([A-Za-z0-9._-]+)`?\s*/\s*`?([A-Za-z0-9._-]+)`?")
SUB_ROW_RE = re.compile(r"^\s*\|\s*`?([A-Za-z0-9._-]+)`?\s*\|\s*`?([A-Za-z0-9._-]+)`?\s*\|")


class Change:
    def __init__(self, repo: str, name: str, path: Path):
        self.repo = repo
        self.name = name
        self.path = path
        self.archived = "archive" in path.parts
        text = ""
        proposal = path / "proposal.md"
        if proposal.is_file():
            text = proposal.read_text(encoding="utf-8", errors="replace")
        self.owner = self._owner(text)
        self.part_of = self._part_of(text)
        self.subs = self._subs(text)

    @staticmethod
    def _owner(text: str) -> str | None:
        m = OWNER_RE.search(text)
        return m.group(1) if m else None

    @staticmethod
    def _part_of(text: str) -> tuple[str, str] | None:
        m = PART_OF_RE.search(text)
        return (m.group(1), m.group(2)) if m else None

    @staticmethod
    def _subs(text: str) -> list[tuple[str, str]]:
        """Rows of the Sub-changes table: | repo | change | what it covers |."""
        block = re.search(r"\*\*Sub-changes\*\*[：:](.*?)(?:\n\n|\Z)", text, re.S)
        if not block:
            return []
        out = []
        for line in block.group(1).splitlines():
            m = SUB_ROW_RE.match(line)
            if m and m.group(1).lower() not in ("repo", "---"):
                out.append((m.group(1), m.group(2)))
        return out

    @property
    def ref(self) -> str:
        return f"{self.repo}/{self.name}"


def opted_in(repos_dir: Path) -> set[str]:
    """Repos that ask for owner declarations, by carrying the rule themselves.

    Self-describing rather than a hardcoded list: a repo joins the convention by
    putting it in its own openspec/config.yaml, and this notices.
    """
    joined = set()
    for repo_dir in sorted(p for p in repos_dir.iterdir() if p.is_dir()):
        config = repo_dir / "openspec" / "config.yaml"
        if config.is_file() and "Owning repo" in config.read_text(
                encoding="utf-8", errors="replace"):
            joined.add(repo_dir.name)
    return joined


def discover(repos_dir: Path) -> list[Change]:
    changes: list[Change] = []
    for repo_dir in sorted(p for p in repos_dir.iterdir() if p.is_dir()):
        base = repo_dir / "openspec" / "changes"
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            if child.name == "archive":
                for archived in sorted(child.iterdir()):
                    if archived.is_dir():
                        changes.append(Change(repo_dir.name, archived.name, archived))
                continue
            changes.append(Change(repo_dir.name, child.name, child))
    return changes


def main() -> int:
    repos_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    if not repos_dir.is_dir():
        sys.exit(f"not a directory: {repos_dir}")

    changes = discover(repos_dir)
    active = [c for c in changes if not c.archived]
    by_ref = {c.ref: c for c in changes}
    joined = opted_in(repos_dir)

    print(f"repos dir: {repos_dir}")
    print(f"scanned:   {len(changes)} change(s) across "
          f"{len({c.repo for c in changes})} repo(s), {len(active)} active")
    print(f"declaring: {', '.join(sorted(joined)) or '(none)'}\n")

    problems: list[str] = []

    # COPY — the same name in more than one repo, with nothing declaring a parent.
    by_name: dict[str, list[Change]] = {}
    for c in active:
        by_name.setdefault(c.name, []).append(c)
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        unlinked = [c for c in group if not c.part_of]
        if len(unlinked) > 1:
            repos = ", ".join(c.repo for c in unlinked)
            problems.append(
                f"  COPY        {name}\n"
                f"              exists in {repos} with no Part of: line.\n"
                f"              A repo either owns a sub-change with its own tasks, or holds\n"
                f"              nothing. There is no 'keep a copy to read' option — the copy\n"
                f"              stops being true and nothing says when."
            )

    for c in active:
        # DANGLING — points at a root that is not there.
        if c.part_of:
            ref = f"{c.part_of[0]}/{c.part_of[1]}"
            root = by_ref.get(ref)
            if root is None:
                problems.append(
                    f"  DANGLING    {c.ref}\n"
                    f"              Part of: {ref}, which does not exist")
            elif root.archived:
                problems.append(
                    f"  PREMATURE   {ref}\n"
                    f"              archived while sub-change {c.ref} is still active")
        # UNDECLARED — nobody owns it. Only for repos that asked to be checked.
        elif not c.owner and c.repo in joined:
            problems.append(
                f"  UNDECLARED  {c.ref}\n"
                f"              no `**Owning repo**` line in proposal.md")

        # MISSING — lists a sub-change that is not there.
        for sub_repo, sub_name in c.subs:
            if f"{sub_repo}/{sub_name}" not in by_ref:
                problems.append(
                    f"  MISSING     {c.ref}\n"
                    f"              lists sub-change {sub_repo}/{sub_name}, which does not exist")

    if not problems:
        print("every cross-repo link resolves.")
        return 0

    print("\n".join(problems))
    print(f"\n{len(problems)} problem(s).")
    print("A cross-repo link is prose until something walks it. `openspec validate`")
    print("cannot see past its own repo, which is why this exists.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
