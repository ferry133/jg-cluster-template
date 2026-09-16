#!/usr/bin/env python3
"""Tests for delivery-check.py's `repo-hygiene` subcommand — #104 (4), batch 2a.

Run: python3 .github/workflows/run-tests.py

No fake tools here: this subcommand only ever runs `git -C <dir>`, so every case
builds a real repository in a temp dir and lets the real git answer. A stub would
be testing the stub — and the defects this check exists for are all about what
git actually records versus what the working copy shows.

Three properties are worth more than the happy path, and each has a mutation in
the PR that turns exactly one of these tests red:

1. **A failed positive control must report "cannot measure", not "clean".**
   `git log --all -- '*cluster.yaml'` returning nothing is also what a wrong
   pathspec, an empty repo or a broken invocation returns. The check asserts the
   same query shape finds `*.md`; if that finds nothing either, the clean result
   above it proves nothing.
2. **The history query must match any path**, not the expected one. jg-jiahd's
   eleven credential-bearing blobs were at `config.gen/cluster.yaml`.
3. **The deep scan must NOT fire on SOPS ciphertext.** Every cluster repo is
   *supposed* to commit `cluster-secrets.sops.yaml` with all these field names
   present and encrypted. Measured on jg-janncotcc 2026-08-22: five fields
   matched, all five values began `ENC[`, and the delivery reported a leak. A
   guard that fires on the correct state gets switched off, and a switched-off
   guard reads exactly like a passing one.
"""

from __future__ import annotations

# Loading the subject with `spec_from_file_location` writes
# `scripts/__pycache__/delivery-check.*.pyc` unless this is set first. That
# cached bytecode is not a tidiness question: CPython reuses a `.pyc` when the
# source mtime (to the second) AND size both match, which is exactly what a
# minimal mutation looks like — so a negative control can report the PREVIOUS
# mutation's result (jgct#96, and #102 was bitten by it).
#
# `.github/workflows/run-tests.py` sets this too, so the sanctioned entry point
# is already clean (measured: 0 `.pyc` after a full run). This line covers the
# other way in, `python3 -m unittest scripts/tests/<file>`, which no runner
# guards. **It cannot prevent this test module's OWN `.pyc`** — that is written
# while unittest imports it, before this line executes. Only `python3 -B` or
# `PYTHONDONTWRITEBYTECODE=1` covers that, and every test file in this directory
# shares the gap, so it is written here rather than fixed silently in one of them.
import sys

sys.dont_write_bytecode = True

import contextlib
import importlib.util
import io
import pathlib
import subprocess
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("dc", ROOT / "scripts" / "delivery-check.py")
dc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dc)

# Looks like a live Cloudflare token; belongs to nobody.
FAKE_TOKEN = "0123456789abcdef0123456789abcdef01234567"


def git(d: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    """Real git, with identity forced so the test does not depend on ~/.gitconfig.

    `-c core.excludesFile=/dev/null` is **redundant defence, not what makes
    these tests hermetic** — measured 2026-09-13 after `[c8c318]` asked for the
    control. What makes them immune is that every `add` below passes `-f`:

        hostile global excludesFile listing `.gitignore`:
          plain `git add .gitignore`  -> stages 0 files   (the config does bite)
          `git add -f .gitignore`     -> stages 1 file    (-f overrides it)
          the 18 tests, override present -> 18 pass
          the 18 tests, override removed -> 18 pass       (so it is not load-bearing)

    An earlier version of this docstring claimed the override was the thing
    keeping the operator's global ignore list out. That was reasoning, written in
    the voice of a measurement. The list is still worth neutralising — a future
    case that drops `-f` would depend on it — but the claim had to match what was
    measured.
    """
    return subprocess.run(
        ["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", "-c", "core.excludesFile=/dev/null", *args],
        capture_output=True, text=True, timeout=60,
    )


@contextlib.contextmanager
def repo(*, ignore: str | None = "cluster.yaml\n", track_ignore: bool = True,
         extra: dict[str, str] | None = None, with_md: bool = True):
    """A committed repository, shaped by what each case needs."""
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d)
        git(p, "init", "-q")
        if with_md:
            (p / "README.md").write_text("# a repo\n")
            git(p, "add", "README.md")
        if ignore is not None:
            (p / ".gitignore").write_text(ignore)
            if track_ignore:
                git(p, "add", "-f", ".gitignore")
        for name, body in (extra or {}).items():
            f = p / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body)
            git(p, "add", "-f", name)
        git(p, "commit", "-q", "-m", "initial")
        yield p


def capture(fn, *a) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


def args_for(p: pathlib.Path, deep: bool = False):
    return types.SimpleNamespace(dir=str(p), deep=deep)


class TestRepoHygiene(unittest.TestCase):
    def test_a_clean_repo_passes(self):
        """The positive control for every refusal below."""
        with repo() as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p))
        self.assertEqual(rc, dc.PASS, out)
        self.assertIn("no *cluster.yaml at any path", out)

    def test_an_untracked_gitignore_is_a_finding(self):
        """jg-jiahd's shape: the rule exists on this machine only, and
        `git check-ignore` — which reads the working copy — says it is fine."""
        with repo(track_ignore=False) as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p))
        self.assertEqual(rc, dc.FAIL, out)
        self.assertIn("NOT tracked", out)

    def test_a_tracked_gitignore_without_the_rule_is_a_finding(self):
        with repo(ignore="*.log\n") as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p))
        self.assertEqual(rc, dc.FAIL, out)
        self.assertIn("no cluster.yaml rule", out)

    def test_cluster_yaml_at_an_unexpected_path_is_still_found(self):
        """The eleven blobs were at `config.gen/cluster.yaml`, not at the root.
        A pathspec without the leading `*` would miss exactly that."""
        with repo(extra={"config.gen/cluster.yaml": "cloudflare_token: x\n"}) as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p))
        self.assertEqual(rc, dc.FAIL, out)
        self.assertIn("appears in history", out)

    def test_untracking_later_does_not_clear_the_history(self):
        """`git rm` makes the file absent from the working copy and from HEAD,
        which is the state someone reports as fixed."""
        with repo(extra={"cluster.yaml": "cloudflare_token: x\n"}) as p:
            git(p, "rm", "-q", "--cached", "cluster.yaml")
            git(p, "commit", "-q", "-m", "untrack it")
            rc, out = capture(dc.check_repo_hygiene, args_for(p))
        self.assertEqual(rc, dc.FAIL, out)
        self.assertIn("Rotate the credentials", out)

    def test_a_failed_positive_control_reports_cannot_measure(self):
        """No `*.md` anywhere: the history query cannot be trusted, so the clean
        `*cluster.yaml` result above it means nothing. This must not read as a
        pass — it is the difference between "nothing there" and "not looking"."""
        with repo(with_md=False) as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p))
        self.assertEqual(rc, dc.UNKNOWN, out)
        self.assertIn("positive control found no *.md", out)

    def test_a_directory_that_is_not_a_repo_is_cannot_measure(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = capture(dc.check_repo_hygiene, args_for(pathlib.Path(d)))
        self.assertEqual(rc, dc.UNKNOWN, out)
        self.assertIn("not a git repository", out)


class TestDeepScan(unittest.TestCase):
    def test_deep_finds_a_credential_at_a_name_nobody_predicted(self):
        with repo(extra={"odd/name.yaml": f"stringData:\n  cloudflare_token: {FAKE_TOKEN}\n"}) as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p, deep=True))
        self.assertEqual(rc, dc.FAIL, out)
        self.assertIn("credential-shaped content", out)

    def test_deep_does_not_fire_on_sops_ciphertext(self):
        """The correct state of every cluster repo. This is the case that made a
        whole delivery report a leak on jg-janncotcc, and the reason the check
        has the exemption at all."""
        body = ("stringData:\n"
                "  cloudflare_token: ENC[AES256_GCM,data:abcd,iv:ef,tag:gh,type:str]\n"
                "  ttyd_credential: ENC[AES256_GCM,data:ijkl,iv:mn,tag:op,type:str]\n")
        with repo(extra={"kubernetes/cluster-secrets.sops.yaml": body}) as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p, deep=True))
        self.assertEqual(rc, dc.PASS, out)
        self.assertIn("control sample recognised", out)

    def test_deep_does_not_fire_on_template_placeholders(self):
        """`${VAR}` and `<your-token>` are documentation. A check that flags the
        templates in this very repo would be switched off by its first user."""
        body = ("stringData:\n"
                "  cloudflare_token: \"${CLOUDFLARE_TOKEN}\"\n"
                "  ttyd_credential: <user:password>\n"
                "  claudecode_postgres_password: changeme-please\n")
        with repo(extra={"templates/secret.yaml": body}) as p:
            rc, out = capture(dc.check_repo_hygiene, args_for(p, deep=True))
        self.assertEqual(rc, dc.PASS, out)


class TestIsRealCredential(unittest.TestCase):
    """The exemptions, as a unit. Each one is a case that would otherwise make
    the scan fire on a correct repository."""

    def test_a_real_looking_value_is_a_credential(self):
        self.assertTrue(dc._is_real_credential(FAKE_TOKEN))

    def test_sops_ciphertext_is_not(self):
        self.assertFalse(dc._is_real_credential("ENC[AES256_GCM,data:abcd,type:str]"))

    def test_a_flux_substitution_is_not(self):
        self.assertFalse(dc._is_real_credential("${CLOUDFLARE_TOKEN}"))

    def test_an_angle_bracket_placeholder_is_not(self):
        self.assertFalse(dc._is_real_credential("<your-token-here>"))

    def test_the_word_change_marks_a_placeholder(self):
        self.assertFalse(dc._is_real_credential("changeme-please"))

    def test_a_short_value_is_not_a_credential(self):
        self.assertFalse(dc._is_real_credential("abc"))

    def test_a_trailing_comment_is_stripped_before_judging(self):
        """`cloudflare_token: ${VAR}  # set in cluster.yaml` is a placeholder;
        reading the comment as part of the value would make it look real."""
        self.assertFalse(dc._is_real_credential("${VAR}  # set in cluster.yaml"))

    def test_the_scanners_own_control_sample_is_recognised(self):
        """If this ever returns empty, every clean deep scan in this repo's
        history stops meaning anything."""
        self.assertTrue(dc._scan_blob_for_secrets(dc._SCAN_CONTROL))


class TestTheDeepScanFindsByContentNotByFilename(unittest.TestCase):
    """#166 — the path axis, which had no coverage at all.

    `_SCAN_CONTROL` above is fed straight to `_scan_blob_for_secrets`, so it
    proves the *matcher* recognises a credential. It never passes through
    `_scan_history_for_secrets`, so it said nothing about whether the scan
    walks to that blob — and for four years of filenames it did not: anything
    that was not `*.yaml`/`*.yml` was skipped while the check reported clean.

    Every case here goes through `_scan_history_for_secrets` against a real
    repository, because that function *is* the thing under test.
    """

    EXTENSIONS = ["yaml", "md", "env", "sh", "json"]

    @staticmethod
    def _history(d: pathlib.Path, *, secret: bool, extensions=None,
                 binary: bool = False) -> None:
        """Commit one file per extension, then delete them all.

        Two traps, both hit before this shape was settled on, both of which
        produce "nothing was scanned" that reads like "nothing was found":

        - **Identical contents collapse into one git object**, so five files
          would leave one blob with one path. Each body is made distinct.
        - The path only appears in `rev-list --objects` for a *reachable*
          object, so the files are committed first and removed second — which
          is also the situation being modelled: a credential committed once
          and deleted afterwards is still in the history.
        """
        for i, ext in enumerate(extensions or TestTheDeepScanFindsByContentNotByFilename.EXTENSIONS):
            body = (f"# distinct-body-{i}\n" + (
                f"stringData:\n  cloudflare_token: {FAKE_TOKEN}{i}\n"
                if secret else f"harmless: value-{i}\n"))
            (d / f"leaked.{ext}").write_text(body)
        if binary:
            # A JPEG's first bytes; `text=True` used to raise UnicodeDecodeError
            # on exactly this, which is a crash and not a finding.
            (d / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" * 8)
        git(d, "add", "-fA")
        git(d, "commit", "-qm", "add")
        for ext in extensions or TestTheDeepScanFindsByContentNotByFilename.EXTENSIONS:
            (d / f"leaked.{ext}").unlink()
        if binary:
            (d / "photo.jpg").unlink()
        git(d, "add", "-fA")
        git(d, "commit", "-qm", "remove")

    def _hits(self, **kw) -> set[str]:
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            git(d, "init", "-q")
            self._history(d, **kw)
            return {path for path, _ in dc._scan_history_for_secrets(str(d))}

    def test_a_credential_in_a_yaml_blob_is_found(self):
        """Positive control. If this goes red the rest of this class proves
        nothing — four Falses and a broken scanner look the same."""
        self.assertIn("leaked.yaml", self._hits(secret=True))

    def test_a_credential_outside_yaml_is_found(self):
        """The defect: `.md`/`.env`/`.sh`/`.json` were invisible.

        Asserted as one set comparison rather than four `assertIn`s so that a
        future narrowing cannot pass by finding some of them.
        """
        self.assertEqual(
            {f"leaked.{e}" for e in self.EXTENSIONS}, self._hits(secret=True))

    def test_a_history_with_no_credentials_is_reported_clean(self):
        """Negative control."""
        self.assertEqual(set(), self._hits(secret=False))

    def test_that_negative_control_can_fail(self):
        """The negative control's own positive control.

        Same builder, same repo shape, one credential added: it must go
        non-empty. Without this, "clean" above is also what a scan that never
        ran returns.
        """
        self.assertNotEqual(set(), self._hits(secret=True))

    def test_a_binary_blob_neither_crashes_nor_hides_the_text_ones(self):
        """Removing the filename filter let binary objects reach the reader.

        Measured on this repo's own history: eight blobs whose bytes are not
        UTF-8, and a `text=True` read raises on the first. A crash mid-scan
        would take the credentials found after it down with it, so the case
        asserts both halves: no exception, and the text hits still arrive.
        """
        self.assertEqual(
            {f"leaked.{e}" for e in self.EXTENSIONS},
            self._hits(secret=True, binary=True))

    def test_a_non_utf8_blob_without_a_nul_is_read_not_raised(self):
        """The NUL guard and `errors="replace"` catch *different* blobs.

        Written after a mutation test found this hole: dropping
        `errors="replace"` broke nothing, because the JPEG in the case above
        contains NUL and is skipped before anything is decoded. A blob can be
        invalid UTF-8 with no NUL in it at all — latin-1 prose, a truncated
        binary — and that one reaches the decoder. Without `errors="replace"`
        it raises, and the credentials found after it are lost with it.
        """
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            git(d, "init", "-q")
            (d / "latin1.txt").write_bytes(b"caf\xe9 " * 8)          # no NUL
            (d / "leaked.md").write_text(
                f"stringData:\n  cloudflare_token: {FAKE_TOKEN}\n")
            git(d, "add", "-fA")
            git(d, "commit", "-qm", "add")
            hits = {path for path, _ in dc._scan_history_for_secrets(str(d))}
        self.assertEqual({"leaked.md"}, hits)

    def test_a_credential_shaped_line_inside_a_binary_blob_is_not_a_leak(self):
        """The one narrowing this keeps, and the only axis it narrows on.

        `#166` is about a narrowing along *filenames*. This one is along
        content: a blob containing NUL is not a YAML document — NUL is not
        legal in one — so a `key: value` match inside it is a byte coincidence
        rather than a pasted credential.

        Measured before keeping it: on this repo's own history the guard
        changes nothing at all (127 hits with it, 127 without, 0.39s vs
        0.44s). It is kept for the class of blob rather than for a number, and
        this case exists so that the claim is falsifiable — remove the guard
        and this goes red. A narrowing nobody can turn red is exactly the
        shape this issue is about.
        """
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            git(d, "init", "-q")
            (d / "blob.bin").write_bytes(
                b"\x00\x01\x02\n"                       # NUL, then a line break
                + f"cloudflare_token: {FAKE_TOKEN}\n".encode()
                + b"\x00\xff")
            (d / "leaked.md").write_text(
                f"stringData:\n  cloudflare_token: {FAKE_TOKEN}\n")
            git(d, "add", "-fA")
            git(d, "commit", "-qm", "add")
            hits = {path for path, _ in dc._scan_history_for_secrets(str(d))}
        # The text one still arrives: this asserts the narrowing, not silence.
        self.assertEqual({"leaked.md"}, hits)

    def test_the_extensionless_case_is_covered_too(self):
        """A filename filter would also miss a file with no extension at all —
        `Dockerfile`, `Makefile`, or a pasted note called `notes`."""
        self.assertEqual({"leaked.notes-no-extension"},
                         self._hits(secret=True, extensions=["notes-no-extension"]))


if __name__ == "__main__":
    unittest.main()
