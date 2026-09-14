#!/usr/bin/env python3
"""Tests for scripts/provision.py — §4.

Run: python3 -m unittest discover -s scripts/tests -v
(stdlib only, on purpose: a test suite that needs a dependency installed is a
test suite that stops running on the machine that most needed it.)

**Why this file is tracked.** §3's equivalent tests were written, passed, and
were never committed — so the checkmarks on 3.2-3.7 rest on a run nobody else
can reproduce. `~/.claude/CLAUDE.md`'s form of the rule: a protection that lives
only on the machine doing the verifying is not a protection, it is a local habit
that reports as one. `git clone && python3 -m unittest` is the question these
files exist to answer.

Two of the cases below are regressions, not designs — they were found by
running the code against live systems, and neither would have been found by
re-reading it. They are marked REGRESSION.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prov", ROOT / "scripts" / "provision.py")
prov = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prov)

LIVE = os.environ.get("PROVISION_LIVE_TESTS") == "1"


class TestDerivedNames(unittest.TestCase):
    """4.4. The one worked example is real: janncot.cc -> jg-janncotcc is the
    name of a cluster that exists, so this is a comparison and not a restatement
    of the rule in a second place."""

    def test_the_measured_example(self):
        n = prov.derive_names("janncot.cc")
        self.assertEqual(n["cluster_name"], "jg-janncotcc")
        self.assertEqual(n["repository_name"], "ferry133/jg-janncotcc")
        self.assertEqual(n["tunnel_name"], "jg-janncotcc")

    def test_names_are_the_same_three(self):
        n = prov.derive_names("acme.tw")
        self.assertEqual(n["cluster_name"], n["tunnel_name"])
        self.assertTrue(n["repository_name"].endswith("/" + n["cluster_name"]))

    def test_tld_distinguishes_two_customers(self):
        self.assertNotEqual(prov.derive_names("acme.tw")["cluster_name"],
                            prov.derive_names("acme.com")["cluster_name"])

    def test_no_dots_survive(self):
        # Omni: "name should only contain letters, digits, dashes and
        # underscores". A rule that kept the dot fails at cluster creation,
        # several steps after everything else committed to the name.
        for d in ("a.b.c.example.com", "x.tw"):
            self.assertNotIn(".", prov.derive_names(d)["cluster_name"])

    def test_case_and_trailing_dot_normalise(self):
        self.assertEqual(prov.derive_names("Example.COM.")["cluster_name"],
                         prov.derive_names("example.com")["cluster_name"])

    def test_refuses_rather_than_mangles(self):
        for bad in ("", "acme", "acme .tw", "acme_ü.tw"):
            with self.assertRaises(prov.NameError_, msg=f"{bad!r} should be refused"):
                prov.derive_names(bad)


class TestTunnelDeletedAt(unittest.TestCase):
    """REGRESSION, measured 2026-08-26.

    `cloudflared tunnel list --output json` gives every row a `deleted_at`, and
    for a LIVE tunnel it is Go's zero time — a non-empty string, therefore
    truthy. The first version filtered on `not t.get("deleted_at")` and so
    reported ABSENT for tunnels it had just listed. ABSENT is the one state the
    driver acts on, so that bug created a second tunnel per re-run: the exact
    failure 4.10 exists to prevent, produced by a check that read as working.

    All four live tunnels on the workstation carried the zero time.
    """

    def test_zero_time_is_not_deleted(self):
        self.assertFalse(prov.tunnel_is_deleted({"deleted_at": "0001-01-01T00:00:00Z"}))

    def test_missing_and_null_are_not_deleted(self):
        self.assertFalse(prov.tunnel_is_deleted({}))
        self.assertFalse(prov.tunnel_is_deleted({"deleted_at": None}))
        self.assertFalse(prov.tunnel_is_deleted({"deleted_at": ""}))

    def test_a_real_timestamp_is_deleted(self):
        self.assertTrue(prov.tunnel_is_deleted({"deleted_at": "2026-08-23T10:00:00Z"}))


class FakeStep(prov.Step):
    def __init__(self, name, states):
        self.name = name
        self.task = "test"
        self._states = list(states)
        self.created = 0

    def observe(self, ctx):
        return prov.Observation(self._states.pop(0), f"{self.name} says so")

    def create(self, ctx):
        self.created += 1
        return []


class TestDriverDecisionTable(unittest.TestCase):
    """4.10 + 4.12. The four-way decision lives in one place so it cannot drift
    between steps; these are the four ways out of it."""

    def drive_with(self, steps, apply_=True):
        old, prov.STEPS = prov.STEPS, steps
        try:
            return prov.drive({"dir": "/nonexistent"}, apply_=apply_)
        finally:
            prov.STEPS = old

    def test_present_is_skipped_which_is_what_makes_a_rerun_converge(self):
        s = FakeStep("a", [prov.PRESENT])
        self.assertEqual(self.drive_with([s]), prov.DONE)
        self.assertEqual(s.created, 0)

    def test_absent_creates_then_reobserves(self):
        s = FakeStep("a", [prov.ABSENT, prov.PRESENT])
        self.assertEqual(self.drive_with([s]), prov.DONE)
        self.assertEqual(s.created, 1)

    def test_create_that_reports_success_but_changed_nothing_is_a_stop(self):
        # `gh repo create` exits 0 against a name already taken elsewhere.
        s = FakeStep("a", [prov.ABSENT, prov.ABSENT])
        self.assertEqual(self.drive_with([s]), prov.REFUSED)

    def test_unmeasurable_never_creates(self):
        # The whole file in one assertion: an unmeasured absence is not an
        # absence, and creating on it is how a second tunnel appears.
        s = FakeStep("a", [prov.UNMEASURABLE])
        self.assertEqual(self.drive_with([s]), prov.UNKNOWN)
        self.assertEqual(s.created, 0)

    def test_conflict_never_creates(self):
        s = FakeStep("a", [prov.CONFLICT])
        self.assertEqual(self.drive_with([s]), prov.REFUSED)
        self.assertEqual(s.created, 0)

    def test_a_stop_stops_the_steps_after_it(self):
        first = FakeStep("a", [prov.UNMEASURABLE])
        second = FakeStep("b", [prov.ABSENT, prov.PRESENT])
        self.assertEqual(self.drive_with([first, second]), prov.UNKNOWN)
        self.assertEqual(second.created, 0, "later steps observe a world nobody described")

    def test_without_apply_nothing_is_created(self):
        s = FakeStep("a", [prov.ABSENT])
        self.assertEqual(self.drive_with([s], apply_=False), prov.DONE)
        self.assertEqual(s.created, 1, "create() is called to print the commands…")
        # …but drive() never runs them; that is asserted by the absence of a
        # re-observation, which would have popped a second state and raised.


class TestMachineTicketMatching(unittest.TestCase):
    """4.1/4.2. Matching is a lookup on a label written at image-build time.
    It is deliberately not similarity over hostname or arrival order: 4.2's
    refusal is only worth something if it is exact."""

    def test_reads_the_label_both_shapes(self):
        self.assertEqual(prov.machine_ticket_label(
            {"metadata": {"labels": {"delivery-ticket": "42"}}}), "42")
        self.assertEqual(prov.machine_ticket_label(
            {"metadata": {"labels": {"delivery-ticket/42": ""}}}), "42")

    def test_unlabelled_machine_is_none_not_a_guess(self):
        for m in ({"metadata": {"labels": {"client": "1"}}},
                  {"metadata": {"labels": {}}},
                  {"metadata": {}},
                  {}):
            self.assertIsNone(prov.machine_ticket_label(m))

    def test_a_similar_label_does_not_match(self):
        self.assertIsNone(prov.machine_ticket_label(
            {"metadata": {"labels": {"delivery-tickets": "42"}}}))


class TestClusterYamlGuard(unittest.TestCase):
    """4.6/4.7. Rendering over another cluster's cluster.yaml produces that
    cluster's tree in this repo, and `task configure` would exit 0."""

    def observe(self, contents, cluster_name="jg-target"):
        with tempfile.TemporaryDirectory() as d:
            if contents is not None:
                (pathlib.Path(d) / "cluster.yaml").write_text(contents)
            return prov.ClusterYamlStep().observe(
                {"dir": d, "cluster_name": cluster_name})

    def test_absent(self):
        self.assertEqual(self.observe(None).state, prov.ABSENT)

    def test_matching(self):
        self.assertEqual(self.observe('cluster_name: "jg-target"\n').state, prov.PRESENT)
        self.assertEqual(self.observe("cluster_name: jg-target\n").state, prov.PRESENT)

    def test_another_clusters_file_is_a_conflict_not_an_overwrite(self):
        o = self.observe('cluster_name: "jg-someoneelse"\n')
        self.assertEqual(o.state, prov.CONFLICT)
        self.assertIn("jg-someoneelse", o.detail)

    def test_no_cluster_name_at_all(self):
        self.assertEqual(self.observe("storage_backend: nfs\n").state, prov.CONFLICT)


class TestHistoryLeakGuard(unittest.TestCase):
    """4.7's half of the runbook's `cluster.yaml` rule, over a real git repo
    built here rather than a recorded fixture — a fixture would encode whatever
    this code already believes `git log --all -- '*cluster.yaml'` prints."""

    def make_repo(self, commit_path: str | None):
        d = tempfile.mkdtemp()
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", d, "init", "-q"], check=True, env=env)
        (pathlib.Path(d) / "README").write_text("x")
        subprocess.run(["git", "-C", d, "add", "README"], check=True, env=env)
        subprocess.run(["git", "-C", d, "commit", "-qm", "init"], check=True, env=env)
        if commit_path:
            p = pathlib.Path(d) / commit_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("cloudflare_token: realish-value-here\n")
            subprocess.run(["git", "-C", d, "add", "-f", commit_path], check=True, env=env)
            subprocess.run(["git", "-C", d, "commit", "-qm", "oops"], check=True, env=env)
            # Untracking is what jcom and jg-jiahd both did, and it is not
            # remediation: the blob stays reachable. The guard must still fire.
            subprocess.run(["git", "-C", d, "rm", "-q", "--cached", commit_path],
                           check=True, env=env)
            subprocess.run(["git", "-C", d, "commit", "-qm",
                            "chore: untrack sensitive config files"], check=True, env=env)
        return d

    def test_clean_history_passes(self):
        d = self.make_repo(None)
        self.assertEqual(prov.ConfigurePushStep().observe({"dir": d}).state, prov.PRESENT)

    def test_the_path_that_actually_leaked_is_caught(self):
        # jcom and jg-jiahd leaked at config.gen/cluster.yaml while the ignore
        # rule and the check both named /cluster.yaml. The glob is the fix.
        d = self.make_repo("config.gen/cluster.yaml")
        o = prov.ConfigurePushStep().observe({"dir": d})
        self.assertEqual(o.state, prov.CONFLICT)

    def test_untracking_does_not_clear_it(self):
        d = self.make_repo("cluster.yaml")
        o = prov.ConfigurePushStep().observe({"dir": d})
        self.assertEqual(o.state, prov.CONFLICT)
        self.assertIn("untrack", o.detail)

    def test_not_a_repo_is_unmeasurable_not_clean(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(prov.ConfigurePushStep().observe({"dir": d}).state,
                             prov.UNMEASURABLE)


class TestNetworkDerivation(unittest.TestCase):
    """4.6. Refusing to pick is the behaviour under test: node_cidr is one
    value, and a wrong one produces a cluster that comes up unreachable, which
    neither the render nor `cue vet` can see."""

    def test_ignores_loopback_and_link_local(self):
        import ipaddress
        addrs = ["127.0.0.1/8", "169.254.1.5/16", "10.9.1.20/24"]
        nets = set()
        for a in addrs:
            i = ipaddress.ip_interface(a)
            if i.ip.is_loopback or i.ip.is_link_local or i.version != 4:
                continue
            nets.add(str(i.network))
        self.assertEqual(nets, {"10.9.1.0/24"})


@unittest.skipUnless(LIVE, "set PROVISION_LIVE_TESTS=1 to run checks that need gh")
class TestLive(unittest.TestCase):
    """The observers that talk to real systems.

    Skipped by default so the suite runs offline — but skipped is not passed,
    and these are the cases that caught the `deleted_at` regression. Run them
    before trusting a change to any observer.
    """

    def test_existing_repo_is_present(self):
        o = prov.UserRepoStep().observe({"repository_name": "ferry133/jg-cluster-template"})
        self.assertEqual(o.state, prov.PRESENT)

    def test_missing_repo_is_absent_with_a_positive_control(self):
        o = prov.UserRepoStep().observe(
            {"repository_name": "ferry133/definitely-not-a-real-repo-8f3a"})
        self.assertEqual(o.state, prov.ABSENT)
        self.assertTrue(o.evidence, "an ABSENT with no positive control is a guess")


class TestStepInputsAreCheckedOnlyWhenActing(unittest.TestCase):
    """4.3 + #129. `omnictl cluster template sync -f <path>` is handed a file
    that nothing in this repo ships. The driver refuses to act on an
    unmeasurable observation of the outside world; `Step.inputs()` is that same
    refusal turned on the driver's own inputs.

    **Where the check lives is the whole design**, and it is a negative
    condition: `plan` and a `run` without `--apply` do not read that file, and
    must not start needing it. A check that fires on a correct "show me what
    you would do" gets switched off, and a switched-off check reads like
    coverage. `test_moving_the_check_into_observe_breaks_plan` is the control
    that proves the tests below can tell the difference — it puts the check in
    the wrong place and watches plan stop.
    """

    class StepWithInput(prov.Step):
        """A step that hands a path to an external command, like 4.3 does."""

        name, task = "needs-a-file", "test"

        def __init__(self, path, states, cmds=None):
            self.path = path
            self._states = list(states)
            self.cmds = cmds if cmds is not None else []
            self.created = 0
            self.observed = 0

        def observe(self, ctx):
            self.observed += 1
            return prov.Observation(self._states.pop(0), "says so")

        def inputs(self, ctx):
            return [self.path]

        def create(self, ctx):
            self.created += 1
            return list(self.cmds)

    class PlainStep(prov.Step):
        """Declares no inputs. Used to ask whether the driver carried on."""

        name, task = "after", "test"

        def __init__(self, states):
            self._states = list(states)
            self.observed = 0

        def observe(self, ctx):
            self.observed += 1
            return prov.Observation(self._states.pop(0), "says so")

        def create(self, ctx):
            return []

    def drive(self, steps, apply_):
        import contextlib
        import io
        out = io.StringIO()
        old, prov.STEPS = prov.STEPS, steps
        try:
            with contextlib.redirect_stdout(out):
                rc = prov.drive({"dir": "/nonexistent"}, apply_=apply_)
        finally:
            prov.STEPS = old
        return rc, out.getvalue()

    # --- the wiring is the real step, not only the fake one ----------------

    def test_the_real_step_declares_the_template_as_its_input(self):
        self.assertEqual(
            prov.OmniClusterStep().inputs({"omni_template": "/w/omni-cluster.yaml"}),
            ["/w/omni-cluster.yaml"],
            "if 4.3 stops declaring it, every test below still passes",
        )

    # --- acting without the file: stop, and say which path ----------------

    def test_applying_without_the_file_stops_and_names_the_path(self):
        missing = "/nonexistent/omni-cluster.yaml"
        s = self.StepWithInput(missing, [prov.ABSENT])
        rc, out = self.drive([s], apply_=True)
        self.assertEqual(rc, prov.UNKNOWN, "not DONE, and not a crash inside omnictl")
        self.assertIn(missing, out, "a stop that does not name the path is a riddle")
        # `create()` has already been called at this point, and that is not a
        # defect: by its own contract it *returns* the commands and runs
        # nothing (`Step.create`: "Returned, not run"), and `drive()` calls it
        # before the apply/plan split so that plan can print them. The
        # assertion that carries the meaning is that nothing was executed —
        # `drive()` marks each command it runs with "$ ".
        self.assertEqual(s.created, 1)
        self.assertNotIn("$ ", out, "no command may be executed after the stop")

    def test_the_file_being_there_is_not_a_stop(self):
        # Negative control. Without it, a check that always stops would pass
        # every assertion above.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "omni-cluster.yaml")
            open(p, "w").write("kind: Cluster\n")
            s = self.StepWithInput(p, [prov.ABSENT, prov.PRESENT])
            rc, _ = self.drive([s], apply_=True)
        self.assertEqual(rc, prov.DONE)
        self.assertEqual(s.created, 1, "the input was there, so acting is correct")

    # --- the negative condition: plan and non-apply run are unchanged -----

    def test_plan_still_prints_would_and_carries_on(self):
        # The condition is NOT "plan exits 0" — plan can exit 0 having skipped
        # the step entirely. What is asserted is that it still says what it
        # would do, with the command, AND that the next step was reached.
        missing = "/nonexistent/omni-cluster.yaml"
        sync = ["omnictl", "cluster", "template", "sync", "-f", missing]
        first = self.StepWithInput(missing, [prov.ABSENT], cmds=[sync])
        after = self.PlainStep([prov.PRESENT])
        rc, out = self.drive([first, after], apply_=False)
        self.assertEqual(rc, prov.DONE)
        self.assertIn("WOULD", out)
        self.assertIn(" ".join(sync), out, "plan must still print the command")
        self.assertEqual(after.observed, 1, "it carried on; it did not stop")

    def test_moving_the_check_into_observe_breaks_plan(self):
        """The control for the test above: put the check in the wrong place
        and watch plan stop. Asserting in a comment that a misplaced check
        would be caught is not a measurement — this runs it."""

        class CheckedInObserve(TestStepInputsAreCheckedOnlyWhenActing.StepWithInput):
            def observe(self, ctx):
                self.observed += 1
                if not os.path.exists(self.path):      # the misplacement
                    return prov.Observation(prov.UNMEASURABLE, f"{self.path} is not here")
                return prov.Observation(self._states.pop(0), "says so")

        missing = "/nonexistent/omni-cluster.yaml"
        first = CheckedInObserve(missing, [prov.ABSENT])
        after = self.PlainStep([prov.PRESENT])
        rc, out = self.drive([first, after], apply_=False)
        self.assertEqual(rc, prov.UNKNOWN, "plan started failing — this is the harm")
        self.assertNotIn("WOULD", out)
        self.assertEqual(after.observed, 0, "and it stopped the steps after it")


if __name__ == "__main__":
    unittest.main()


class TestIdentity(unittest.TestCase):
    """5.3. The interesting case is the unset one: `claudecode_allowed_emails`
    absent renders as auth0.json's list, which carries the operator's addresses
    — so unset and 'deliberately empty' are the same text in cluster.yaml and
    different clusters in production."""

    def run_identity(self, contents):
        import argparse
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "cluster.yaml").write_text(contents)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = prov.cmd_identity(argparse.Namespace(dir=d))
            return rc, out.getvalue()

    BASE = 'cluster_name: "jg-t"\ncloudflare_domain: "cust.tw"\n'

    def test_unset_is_refused_not_treated_as_empty(self):
        rc, out = self.run_identity(self.BASE)
        self.assertEqual(rc, prov.REFUSED)
        self.assertIn("auth0.json", out)

    def test_customer_domain_addresses_pass(self):
        rc, out = self.run_identity(
            self.BASE + 'claudecode_allowed_emails:\n  - "owner@cust.tw"\n')
        self.assertEqual(rc, prov.DONE)
        self.assertIn("this cluster's own domain", out)

    def test_a_foreign_address_is_surfaced_for_a_decision(self):
        # Not a failure: an operator address may be correct for a bench run and
        # wrong at handover, and only a person knows which this is.
        rc, out = self.run_identity(
            self.BASE + 'claudecode_allowed_emails:\n  - "operator@gmail.com"\n')
        self.assertEqual(rc, prov.DONE)
        self.assertIn("not cust.tw", out)

    def test_a_machine_shaped_address_is_refused(self):
        for addr in ("svc-bot@cust.tw", "noreply@cust.tw", "automation@cust.tw"):
            rc, _ = self.run_identity(
                self.BASE + f'claudecode_allowed_emails:\n  - "{addr}"\n')
            self.assertEqual(rc, prov.REFUSED, addr)

    def test_missing_cluster_yaml_is_unknown(self):
        import argparse
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(prov.cmd_identity(argparse.Namespace(dir=d)), prov.UNKNOWN)


class TestTemplateResidue(unittest.TestCase):
    """4.4. Measured 2026-08-26 across three real repos — two clean, one not —
    so this is a discriminating check and not one that always says the same
    thing. jg-jiahd tracks `docs/` and `openspec/`; the template and
    jg-janncotcc track neither."""

    def repo_with(self, dirs):
        import subprocess
        d = tempfile.mkdtemp()
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", d, "init", "-q"], check=True, env=env)
        # A root-level file so the no-subdirectory case still has a commit —
        # otherwise that test measures `git commit` refusing an empty tree
        # rather than the check refusing to call an unreadable repo clean.
        (pathlib.Path(d) / "README.md").write_text("x\n")
        for sub in dirs:
            p = pathlib.Path(d) / sub / "f.yaml"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x: 1\n")
        subprocess.run(["git", "-C", d, "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", d, "commit", "-qm", "init"], check=True, env=env)
        return d

    def residue(self, d):
        import argparse
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = prov.cmd_template_residue(argparse.Namespace(dir=d))
        return rc, out.getvalue()

    def test_a_cluster_repos_own_directories_pass(self):
        rc, _ = self.residue(self.repo_with(["kubernetes", "templates", "scripts"]))
        self.assertEqual(rc, prov.DONE)

    def test_the_trees_that_actually_leaked_are_caught(self):
        rc, out = self.residue(self.repo_with(["kubernetes", "openspec", "docs"]))
        self.assertEqual(rc, prov.REFUSED)
        self.assertIn("openspec", out)
        self.assertIn("docs", out)

    def test_a_tree_nobody_predicted_is_caught_too(self):
        # The point of asking "what is here" rather than "is openspec here":
        # the next tree the template grows will not be called openspec.
        rc, out = self.residue(self.repo_with(["kubernetes", "incident-reports"]))
        self.assertEqual(rc, prov.REFUSED)
        self.assertIn("incident-reports", out)

    def test_a_repo_with_no_subdirectories_is_unknown_not_clean(self):
        rc, _ = self.residue(self.repo_with([]))
        self.assertEqual(rc, prov.UNKNOWN)

    def test_not_a_repo_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            rc, _ = self.residue(d)
            self.assertEqual(rc, prov.UNKNOWN)
