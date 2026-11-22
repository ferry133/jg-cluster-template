#!/usr/bin/env python3
"""chamber_mode turns on jg-base's im/chamber component and CHAMBER_MODE; the credential renders Secret im-chamber; nothing else moves.

jgct#263 (jg-base#248, sub-change im-chamber-identity; ferry133 approved the
four-point design 2026-11-22). On real makejinja renders of the fixtures
check-tenant-render.py maintains:

1. **Off, no change**: no fixture -- nor the im-on fixture with an explicit
   `chamber_mode: off` -- renders CHAMBER_MODE, `components` on any patch,
   the kubernetes/chamber directory or Kustomization
   claude-code-chamber-secret. With `--against <ref>` each is byte-identical
   to the template at <ref>.
2. **A mode, no credential** (observe and deliver, on im/enabled and on
   im/netdev): claude-code-im's patch keeps its path and gains exactly
   `components: [../chamber]`; CHAMBER_MODE is the mode; no Secret, no
   Kustomization; nothing outside cluster-secrets and ks.yaml differs from
   the same cluster with chamber off.
3. **A mode with the credential**: Kustomization claude-code-chamber-secret
   applies ./kubernetes/chamber with sops after cluster-apps-base; that
   directory lists im-chamber.sops.yaml; Secret im-chamber is in `claudecode`
   with exactly `token` and `url`, carrying the fixture's values; neither
   value is in any other file; and only ks.yaml and the two new files differ
   from the credential-less render.
4. **Refusals**, each for its own reason and with no credential in the
   message: a mode on im/disabled, a credential with mode off, one credential
   without the other, a token on two lines, a url that is not https. cue vet
   refuses an unknown mode and accepts the good scenario.

The disabled-position half of point 4 of the design ("never `components` on
im/disabled") is held twice: plugin.py refuses the combination (case
mode-on-disabled), and case 1 covers the im/disabled fixture rendering no
`components`. The template's own `position != 'disabled'` condition is not
reachable through plugin.py, so it has no case of its own here.

Exit 0 pass, 1 fail, 2 could not measure. A failure wins.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tr = _load("tr", "check-tenant-render.py")
nr = _load("nr", "check-netdev-render.py")

CS = tr.CS
KS = tr.KS
SECRET = "kubernetes/chamber/im-chamber.sops.yaml"
CKZ = "kubernetes/chamber/kustomization.yaml"
KS_NAME = "claude-code-chamber-secret"
IM_BASE = "./kubernetes/apps/base/claudecode/claude-code/im"
TOKEN = "placeholder-chamber-token"
URL = "https://chamber.example.invalid"
CREDS = dict(chamber_token=TOKEN, chamber_url=URL)
# The fixture with the base im on (a mode on im/disabled is refused).
BASE = "appliance-instances-auth0"
DISABLED = "appliance-minimal"


def fixture(name: str) -> dict:
    f = next((f for n, f, _ in tr.FIXTURES if n == name), None)
    if f is None:
        raise tr.CannotMeasure(f"fixture {name!r} is gone from check-tenant-render.py")
    return dict(f)


def cs_data(files: dict[str, bytes]) -> dict:
    for d in tr.docs(files[CS]):
        if tr.ident(d) == ("Secret", "cluster-secrets"):
            return d.get("stringData") or {}
    return {}


def patches(files: dict[str, bytes]) -> list[tuple[str, dict]]:
    out = []
    for d in tr.docs(files[KS]):
        for p in (d.get("spec") or {}).get("patches") or []:
            body = tr.yq_value(p.get("patch", "")) if isinstance(p.get("patch"), str) else None
            out.append(((p.get("target") or {}).get("name"), body if isinstance(body, dict) else {}))
    return out


def im_spec(files: dict[str, bytes]) -> dict | None:
    for name, body in patches(files):
        if name == "claude-code-im":
            return body.get("spec") or {}
    return None


def chamber_ks(files: dict[str, bytes]) -> dict | None:
    return {tr.ident(d): d for d in tr.docs(files.get(KS, b""))}.get(("Kustomization", KS_NAME))


def check_off(name: str, files: dict[str, bytes]) -> list[str]:
    bad = []
    if "CHAMBER_MODE" in cs_data(files):
        bad.append(f"[{name}] chamber off, yet cluster-secrets has CHAMBER_MODE")
    with_components = [n for n, body in patches(files) if "components" in (body.get("spec") or {})]
    if with_components:
        bad.append(f"[{name}] chamber off, yet patches carry components: {with_components}")
    if SECRET in files or CKZ in files:
        bad.append(f"[{name}] chamber off, yet kubernetes/chamber rendered")
    if chamber_ks(files) is not None:
        bad.append(f"[{name}] chamber off, yet Kustomization {KS_NAME} rendered")
    return bad


def check_mode(label: str, off: dict[str, bytes], files: dict[str, bytes],
               mode: str, position: str) -> list[str]:
    bad = []
    spec = im_spec(files)
    if spec is None:
        return [f"[{label}] no claude-code-im patch"]
    if spec.get("path") != f"{IM_BASE}/{position}":
        bad.append(f"[{label}] claude-code-im path {spec.get('path')!r}, expected {IM_BASE}/{position}")
    if spec.get("components") != ["../chamber"]:
        bad.append(f"[{label}] claude-code-im components {spec.get('components')!r}, expected ['../chamber']")
    if (im_spec(off) or {}).get("path") != spec.get("path"):
        bad.append(f"[{label}] turning chamber on moved claude-code-im's path")
    others = [n for n, body in patches(files)
              if n != "claude-code-im" and "components" in (body.get("spec") or {})]
    if others:
        bad.append(f"[{label}] components on patches other than claude-code-im: {others}")
    got = cs_data(files).get("CHAMBER_MODE")
    if got != mode:
        bad.append(f"[{label}] CHAMBER_MODE {got!r}, expected {mode!r}")
    if SECRET in files or CKZ in files or chamber_ks(files) is not None:
        bad.append(f"[{label}] no credential, yet the Secret or its Kustomization rendered")
    stray = [d for d in tr.diff_names(off, files) if d not in {f"differs: {CS}", f"differs: {KS}"}]
    if stray:
        bad.append(f"[{label}] the mode changed more than cluster-secrets and ks.yaml: {stray}")
    return bad


def check_secret(label: str, quiet: dict[str, bytes], files: dict[str, bytes]) -> list[str]:
    bad = []
    ks = chamber_ks(files)
    if ks is None:
        bad.append(f"[{label}] no Kustomization {KS_NAME} -- nothing would apply the Secret")
    else:
        spec = ks.get("spec") or {}
        if spec.get("path") != "./kubernetes/chamber":
            bad.append(f"[{label}] {KS_NAME} path {spec.get('path')!r}")
        if (spec.get("decryption") or {}).get("provider") != "sops":
            bad.append(f"[{label}] {KS_NAME} does not decrypt with sops")
        if [d.get("name") for d in spec.get("dependsOn") or []] != ["cluster-apps-base"]:
            bad.append(f"[{label}] {KS_NAME} does not depend on cluster-apps-base alone")
    listed = next((d.get("resources") or [] for d in tr.docs(files.get(CKZ, b""))), [])
    if listed != ["im-chamber.sops.yaml"]:
        bad.append(f"[{label}] {CKZ} lists {listed}, expected ['im-chamber.sops.yaml']")
    sec = {tr.ident(d): d for d in tr.docs(files.get(SECRET, b""))}.get(("Secret", "im-chamber"))
    if sec is None:
        bad.append(f"[{label}] Secret im-chamber not rendered in {SECRET}")
    else:
        if sec.get("metadata", {}).get("namespace") != "claudecode":
            bad.append(f"[{label}] Secret im-chamber not in claudecode")
        sd = sec.get("stringData") or {}
        if sorted(sd) != ["token", "url"]:
            bad.append(f"[{label}] Secret im-chamber keys {sorted(sd)}, expected ['token', 'url']")
        elif sd["token"] != TOKEN or sd["url"] != URL:
            bad.append(f"[{label}] Secret im-chamber does not carry the fixture's values")
    for value, what in ((TOKEN, "token"), (URL, "url")):
        elsewhere = sorted(n for n, b in files.items() if n != SECRET and value.encode() in b)
        if elsewhere:
            bad.append(f"[{label}] the {what} is also in {elsewhere}")
    allowed = {f"differs: {KS}", f"only in second: {SECRET}", f"only in second: {CKZ}"}
    stray = [d for d in tr.diff_names(quiet, files) if d not in allowed]
    if stray:
        bad.append(f"[{label}] the credential changed more than its three files: {stray}")
    return bad


REFUSALS = [
    # (name, fixture builder, reason substring)
    ("mode-on-disabled", lambda: dict(fixture(DISABLED), chamber_mode="observe"),
     "im/disabled path"),
    ("creds-mode-off", lambda: dict(fixture(BASE), **CREDS),
     "but chamber_mode is off"),
    ("token-only", lambda: dict(fixture(BASE), chamber_mode="deliver", chamber_token=TOKEN),
     "is missing chamber_url"),
    ("url-only", lambda: dict(fixture(BASE), chamber_mode="deliver", chamber_url=URL),
     "is missing chamber_token"),
    ("token-two-lines", lambda: dict(fixture(BASE), chamber_mode="deliver",
                                     chamber_token=TOKEN + "\nx", chamber_url=URL),
     "span more than one line"),
    ("url-not-https", lambda: dict(fixture(BASE), chamber_mode="deliver",
                                   chamber_token=TOKEN, chamber_url="http://chamber.example.invalid"),
     "must start with https://"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", type=Path, default=ROOT)
    ap.add_argument("--against", metavar="REF")
    args = ap.parse_args()
    failures: list[str] = []
    passed = 0
    refusals = 0
    try:
        base = fixture(BASE)
        with tempfile.TemporaryDirectory(prefix="chamber-render.") as tmp:
            key = Path(tmp) / "age.key"
            subprocess.run([tr.tool("age-keygen"), "-o", str(key)], capture_output=True, check=True)
            ref_tree = None
            if args.against:
                ref_tree = Path(tmp) / "ref"
                ref_tree.mkdir()
                tr.checkout(args.against, ref_tree)

            def render(f):
                return tr.render(args.tree, f, [], key)

            # 1. off
            population = [(n, f, nodes) for n, f, nodes in tr.FIXTURES]
            population.append(("explicit-off", dict(base, chamber_mode="off"), []))
            for name, fx, nodes in population:
                try:
                    files = tr.render(args.tree, fx, nodes, key)
                    before = tr.render(ref_tree, fx, nodes, key) if ref_tree else None
                except RuntimeError as e:
                    failures.append(f"[{name}] render failed: {e}")
                    continue
                bad = check_off(name, files)
                if before is not None:
                    bad += [f"[{name}] differs from {args.against}: {d}"
                            for d in tr.diff_names(before, files)]
                failures += bad
                if not bad:
                    passed += 1
                    print(f"ok  [{name}] no CHAMBER_MODE, no components, no chamber directory, no {KS_NAME}"
                          + (f"; byte-identical to {args.against}" if before is not None else ""))

            # 2. a mode without the credential, on both im positions it can join
            netdev = dict(base, **nr.READER)
            for pos_label, pos_base, position in (("enabled", base, "enabled"),
                                                  ("netdev", netdev, "netdev")):
                off = render(pos_base)
                for mode in ("observe", "deliver"):
                    label = f"{mode}-{pos_label}"
                    bad = check_mode(label, off, render(dict(pos_base, chamber_mode=mode)), mode, position)
                    failures += bad
                    if not bad:
                        passed += 1
                        print(f"ok  [{label}] claude-code-im stays on im/{position} and gains "
                              f"components [../chamber]; CHAMBER_MODE={mode}; nothing else moved")

            # 3. the credential
            quiet = render(dict(base, chamber_mode="deliver"))
            files = render(dict(base, chamber_mode="deliver", **CREDS))
            bad = check_secret("deliver-creds", quiet, files)
            failures += bad
            if not bad:
                passed += 1
                print(f"ok  [deliver-creds] {KS_NAME} applies im-chamber in claudecode with token and url, "
                      "carrying the fixture's values; nothing else moved")

            # 4. refusals
            for name, build, reason in REFUSALS:
                try:
                    render(build())
                except RuntimeError as e:
                    msg = str(e)
                    if reason not in msg:
                        failures.append(f"[{name}] refused, but not for its own reason "
                                        f"(no {reason!r}): {msg[-200:]}")
                    elif TOKEN in msg:
                        failures.append(f"[{name}] refused, and the message carries the token")
                    else:
                        refusals += 1
                        print(f"ok  [{name}] refused: {reason!r}")
                    continue
                failures.append(f"[{name}] rendered; it must be refused ({reason!r})")
            for name, fx, accept in (
                ("vet-deliver", dict(base, chamber_mode="deliver", **CREDS), True),
                ("vet-bad-mode", dict(base, chamber_mode="on"), False),
            ):
                problem = tr.vet(args.tree, fx, [])
                if (problem is None) != accept:
                    failures.append(f"[{name}] cue vet {'refused' if problem else 'accepted'} it"
                                    + (f": {problem}" if problem and TOKEN not in problem else ""))
                else:
                    print(f"ok  [{name}] cue vet {'accepts' if accept else 'refuses'}")
    except tr.CannotMeasure as e:
        if failures:
            print("\n".join("FAIL " + f for f in failures))
            return 1
        print(f"COULD NOT MEASURE: {e}")
        return 2
    except RuntimeError as e:
        failures.append(f"a good scenario failed to render (guard or template defect): {e}")
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print(f"PASS -- {passed} render cases"
          + (f" (off cases byte-identical to {args.against})" if args.against else "")
          + f"; {refusals}/{len(REFUSALS)} refusals each for its own reason; 2 cue vet verdicts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
