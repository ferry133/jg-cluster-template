"""check-tenant-render.py can tell a tenant-free render from one that is not.

Each case copies the template inputs into a temporary tree, applies one
mutation, and runs the guard on it with `--tree`. The mutation is asserted to
have landed before the guard runs: an edit that did not apply returns the same
exit 0 as a guard that cannot see it.

Case 0 is the unmutated copy and must pass. If the harness itself is broken,
every mutation would go red and read as "every mutation is caught".

Needs makejinja, cue and age-keygen on PATH (CI installs them with mise). A
missing tool makes the guard exit 2, which fails every case here: a skipped
test reads green.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "check-tenant-render.py"
KS = Path("templates/config/kubernetes/flux/cluster/ks.yaml.j2")
SCHEMA = Path(".taskfiles/template/resources/cluster.schema.cue")
COPY = ["templates", "makejinja.toml", "trello-notifier.sample.yaml",
        ".taskfiles/template/resources"]


class TenantRenderGuard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tenant-guard-test.")
        self.tree = Path(self._tmp.name)
        for rel in COPY:
            src, dst = ROOT / rel, self.tree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=True)
            else:
                shutil.copy2(src, dst)

    def tearDown(self):
        self._tmp.cleanup()

    def run_guard(self, *extra, env=None):
        proc = subprocess.run([sys.executable, str(GUARD), "--tree", str(self.tree), *extra],
                              capture_output=True, text=True, env=env)
        return proc.returncode, proc.stdout + proc.stderr

    def edit(self, rel: Path, old: str, new: str):
        path = self.tree / rel
        text = path.read_text()
        self.assertIn(old, text, f"mutation anchor not found in {rel}")
        path.write_text(text.replace(old, new, 1))
        self.assertNotEqual(path.read_text(), text, "mutation did not change the file")

    def append(self, rel: Path, tail: str):
        path = self.tree / rel
        before = path.read_text() if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((before or "") + tail)
        self.assertNotEqual(path.read_text(), before, "mutation did not change the file")

    # 0 ---------------------------------------------------------------------
    def test_0_unmutated_copy_passes(self):
        rc, out = self.run_guard()
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)

    # 1 ---------------------------------------------------------------------
    def test_1_render_that_reacts_to_empty_app_repos_fails(self):
        self.append(KS, "\n#% if app_repos is defined %#\n---\n# reacts to app_repos: []\n#% endif %#\n")
        rc, out = self.run_guard()
        self.assertEqual(rc, 1, out)
        self.assertIn("absent vs `[]` differ", out)
        self.assertIn("differs: kubernetes/flux/cluster/ks.yaml", out)

    # 2 ---------------------------------------------------------------------
    def test_2_unconditional_tenants_file_fails(self):
        self.append(Path("templates/config/kubernetes/tenants/marker.yaml"),
                    "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: marker\n")
        rc, out = self.run_guard()
        self.assertEqual(rc, 1, out)
        self.assertIn("kubernetes/tenants/marker.yaml: a tenants/ path", out)

    # 3 ---------------------------------------------------------------------
    def test_3_unconditional_cluster_tenants_kustomization_fails(self):
        self.append(KS, "\n---\napiVersion: kustomize.toolkit.fluxcd.io/v1\nkind: Kustomization\n"
                        "metadata:\n  name: cluster-tenants\n  namespace: flux-system\n")
        rc, out = self.run_guard()
        self.assertEqual(rc, 1, out)
        self.assertIn("contains `name: cluster-tenants`", out)

    # 4 ---------------------------------------------------------------------
    def test_4_against_catches_a_deleted_line(self):
        # Whole-line deletion, the shape refactors and merge conflicts produce.
        self.edit(KS, "  deletionPolicy: WaitForTermination\n  interval: 1h\n  path: ./kubernetes/apps/extras/",
                  "  interval: 1h\n  path: ./kubernetes/apps/extras/")
        rc, out = self.run_guard("--against", "HEAD")
        self.assertEqual(rc, 1, out)
        self.assertIn("render differs from HEAD", out)
        # Fixtures without extras render no extras block, so only some fixtures differ.
        self.assertIn("ok  [appliance-minimal]", out)

    # 5 ---------------------------------------------------------------------
    def test_5_invalid_fixture_is_reported_as_a_guard_defect(self):
        self.edit(SCHEMA, 'storage_backend: "local-path" | "nfs" | "replicated"',
                  'storage_backend: "replicated"')
        rc, out = self.run_guard()
        self.assertEqual(rc, 1, out)
        self.assertIn("fixture fails cue vet (guard defect)", out)

    # 6 ---------------------------------------------------------------------
    def test_6_missing_makejinja_is_could_not_measure(self):
        self.assertIsNotNone(shutil.which("makejinja"), "makejinja must be on PATH for this suite")
        # Drop every PATH entry that holds a makejinja -- mise can put more than
        # one on PATH (the python install and the pipx one).
        keep = [p for p in os.environ["PATH"].split(os.pathsep)
                if p and not (Path(p) / "makejinja").exists()]
        env = dict(os.environ, PATH=os.pathsep.join(keep))
        self.assertIsNone(shutil.which("makejinja", path=env["PATH"]),
                          "could not hide makejinja from PATH")
        rc, out = self.run_guard(env=env)
        self.assertEqual(rc, 2, out)
        self.assertIn("COULD NOT MEASURE", out)


if __name__ == "__main__":
    unittest.main()
