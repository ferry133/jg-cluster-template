#!/usr/bin/env python3
"""Assert every `handover` cell's three states, including the two nobody runs.

`delivery-check.py handover` decides a cluster is fit to hand over, and its
cells mostly cannot run anywhere but in front of a real cluster. So the branch
that gets exercised in practice is the happy one, and **the 1 and the 2 paths
are the ones a defect would hide in** -- a cell that can only ever return 0 or
crash reads, from Step 5, exactly like a cell that measured something.

This stands in for the cluster: the cells' I/O helpers (`_secret_values`,
`_newest_completed_job_log`, `_dig`, `_doh_a`) are replaced with functions that
return a chosen shape, and each cell's answer is compared against a written-down
expectation. It runs in a bare checkout, in CI, with no cluster and no network.

Two of the cases are not about right and wrong answers but about output: cell 10
holds an SMTP password and cell 11 a healthchecks capability URL, and neither
may appear in what this prints into a handover note. Those two assert the
absence of a recognisable value AND that the same value is present in the
fixture -- an absence with no positive control is just a grep that missed.

It also carries jgct#104's lesson: the negative controls for PR#103 existed
only on one laptop. A control nobody can re-run is a control that will not be
re-run.

Exit 0 if every case matches its expectation, 1 otherwise.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_delivery_check():
    """Import delivery-check.py by path, without writing bytecode.

    No bytecode: this file exists to be run against a MUTATED delivery-check.py
    (that is how anyone shows it can still tell right from wrong), and CPython
    accepts a cached .pyc when the source mtime (one-second resolution) AND
    size still match -- which is exactly what a minimal mutation looks like
    (jgct#96).
    """
    sys.dont_write_bytecode = True
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(
        "_dc", ROOT / "scripts" / "delivery-check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    m = load_delivery_check()
    failed = 0
    checked = 0

    def A(**kw):
        d = dict(dir=".", domain="example.com", instance="im", repo=None,
                 pubkey="x", kubeconfig="/nonexistent/kubeconfig",
                 token_env="NO_TOKEN_HERE", tunnel_credentials="t.json",
                 auth0_json="auth0.json", resolver=None, trigger=False)
        d.update(kw)
        return types.SimpleNamespace(**d)

    def check(label, got, want_rc, want_why=None):
        nonlocal failed, checked
        checked += 1
        rc, note, why = got
        okrc = rc == want_rc
        okwhy = (want_why is None or why == want_why
                 or (not isinstance(why, str) and why and want_why in why))
        if okrc and okwhy:
            print(f"PASS  {label}  (rc={rc}, why={why})")
        else:
            print(f"FAIL  {label}")
            print(f"        got rc={rc} why={why}, wanted rc={want_rc} why={want_why}")
            print(f"        note: {note[:160]}")
            failed += 1
        return note


        rc, note, why = got

    # ---- cell 6
    m._secret_values = lambda a, ns, n: (None, "no --kubeconfig: this run cannot see the cluster")
    check("6 無 kubeconfig", m.cell_node_dns_path(A(kubeconfig=None)), 2, m.NEED_PLACE)
    m._secret_values = lambda a, ns, n: ({"NODE_DNS_PATH": ""}, None)
    check("6 NODE_DNS_PATH 空", m.cell_node_dns_path(A()), 1)
    m._secret_values = lambda a, ns, n: ({"NODE_DNS_PATH": "lan"}, None)
    check("6 lan 但沒給 --resolver", m.cell_node_dns_path(A()), 2, m.NEED_TOOL)
    m._dig = lambda r, n, timeout=5: ((["1.2.3.4"], None) if n == "ghcr.io" else (["10.0.0.5"], None))
    check("6 兩題都答", m.cell_node_dns_path(A(resolver="10.9.1.1")), 0)
    m._dig = lambda r, n, timeout=5: ((["1.2.3.4"], None) if n == "ghcr.io" else ([], None))
    n = check("6 只答公開名（叢集自己的 k8s-gateway 形狀）", m.cell_node_dns_path(A(resolver="10.9.1.1")), 1)

    m._dig = lambda r, n, timeout=5: (([], None) if n == "ghcr.io" else (["10.0.0.5"], None))
    check("6 只答內部名", m.cell_node_dns_path(A(resolver="10.9.1.1")), 1)

    # ---- cell 7
    m._newest_completed_job_log = lambda a: (None, "", "no --kubeconfig: this run cannot see the cluster", m.NEED_PLACE)
    check("7 無 kubeconfig", m.cell_daily_check_ran(A(kubeconfig=None)), 2, m.NEED_PLACE)
    m._newest_completed_job_log = lambda a: (None, "", "no completed daily-check Job", m.NEED_TOOL)
    check("7 從沒跑過", m.cell_daily_check_ran(A()), 2, m.NEED_TOOL)
    m._newest_completed_job_log = lambda a: ("j1", "", "job/j1 completed but its log is gone", m.NEED_TOOL)
    check("7 跑過但 pod 被回收", m.cell_daily_check_ran(A()), 2, m.NEED_TOOL)
    m._newest_completed_job_log = lambda a: ("j1", "➖ LAN resolves internal names — NODE_DNS_PATH is unset\n", None, None)
    n = check("7 有那一列但是 ➖", m.cell_daily_check_ran(A()), 1)

    m._newest_completed_job_log = lambda a: ("j1", "✅ LAN resolves internal names (10.9.1.30)\n", None, None)
    check("7 有那一列且量到了", m.cell_daily_check_ran(A()), 0)
    m._newest_completed_job_log = lambda a: ("j1", "not configured\n", None, None)
    check("7 log 裡完全沒有那一列", m.cell_daily_check_ran(A()), 2, m.NEED_TOOL)

    # ---- cell 10 / 11
    full = {"SMTP_HOST": "smtp.gmail.com", "SMTP_USERNAME": "u@x", "SMTP_PASSWORD": "PWSECRET",
            "SMTP_FROM": "f@x", "NOTIFY_EMAIL_TO": "a@b", "HEALTHCHECKS_PING_URL": "https://hc.io/UUIDSECRET"}
    m._secret_values = lambda a, ns, n: ({**full, "SMTP_PASSWORD": ""}, None)
    check("10 少一把", m.cell_daily_check_configured(A()), 1)
    m._secret_values = lambda a, ns, n: (full, None)
    n = check("10 齊全", m.cell_daily_check_configured(A()), 0)
    checked += 1
    if "PWSECRET" in n:
        print("FAIL  cell 10 printed the SMTP password into its own output")
        failed += 1
    elif "PWSECRET" not in str(full):
        print("FAIL  the fixture has no recognisable password — the absence above")
        print("        proves nothing, which is the shape this file is about")
        failed += 1
    else:
        print("PASS  cell 10 does not print the SMTP password (and the fixture has one)")
    m._secret_values = lambda a, ns, n: ({**full, "HEALTHCHECKS_PING_URL": ""}, None)
    check("11 ping URL 空", m.cell_dead_man_switch(A()), 1)
    m._secret_values = lambda a, ns, n: ({**full, "HEALTHCHECKS_PING_URL": "http://hc.io/x"}, None)
    check("11 不是 https", m.cell_dead_man_switch(A()), 1)
    m._secret_values = lambda a, ns, n: (full, None)
    n = check("11 已設", m.cell_dead_man_switch(A()), 0)
    checked += 1
    if "UUIDSECRET" in n:
        print("FAIL  cell 11 printed the healthchecks capability URL")
        failed += 1
    elif "UUIDSECRET" not in str(full):
        print("FAIL  the fixture has no recognisable URL — the absence above proves nothing")
        failed += 1
    else:
        print("PASS  cell 11 does not print the ping URL (and the fixture has one)")

    # ---- cell 12
    m._newest_completed_job_log = lambda a: (None, "", "no completed daily-check Job", m.NEED_TOOL)
    check("12 沒有可讀的執行", m.cell_recipients_readback(A()), 2, m.NEED_TOOL)
    m._newest_completed_job_log = lambda a: ("j1", "==> Sending email to ops@x.com\nEmail sent successfully.\n", None, None)
    check("12 寄出且被接受", m.cell_recipients_readback(A()), 0, m.NEED_HUMAN)
    m._newest_completed_job_log = lambda a: ("j1", "==> Sending email to ops@x.com\nWARNING: msmtp returned non-zero.\n", None, None)
    check("12 寄出但沒送達", m.cell_recipients_readback(A()), 1)

    # ---- cell 13
    m._secret_values = lambda a, ns, n: ({"BACKUP_R2_ENDPOINT": ""}, None)
    check("13 叢集上是空的", m.cell_r2_endpoint(A()), 2, m.NEED_HUMAN)
    m._secret_values = lambda a, ns, n: ({"BACKUP_R2_ENDPOINT": "http://10.9.1.12:9000"}, None)
    n = check("13 http:// 的 LAN 位址（jg-janncotcc 那個實例）", m.cell_r2_endpoint(A()), 1)

    m._doh_a = lambda name: ((["104.16.1.1"], None) if name == "cloudflare.com" else (["10.9.1.12"], None))
    m._secret_values = lambda a, ns, n: ({"BACKUP_R2_ENDPOINT": "https://minio.lan.example.com"}, None)
    check("13 https 但解到私有位址", m.cell_r2_endpoint(A()), 1)
    m._doh_a = lambda name: (["104.16.1.1"], None)
    m._secret_values = lambda a, ns, n: ({"BACKUP_R2_ENDPOINT": "https://x.r2.cloudflarestorage.com"}, None)
    check("13 出貨值", m.cell_r2_endpoint(A()), 0)
    m._doh_a = lambda name: ([], "DoH query failed: boom")
    check("13 正對照本身壞了 → 不能回 FAIL", m.cell_r2_endpoint(A()), 2, m.NEED_TOOL)

    print()
    if failed:
        print(f"{failed} of {checked} cases did not match.")
        print("Each handover cell has three answers and only one of them gets")
        print("exercised in front of a real cluster. A cell that lost its 1 or")
        print("its 2 still returns 0 on a good day, which is how it stays lost.")
        return 1
    print(f"ok — {checked} cases match, including both secret-leak controls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
