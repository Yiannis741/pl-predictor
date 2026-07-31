# -*- coding: utf-8 -*-
"""
===============================================================================
ΑΓΓΕΛΙΑΦΟΡΟΣ  (bridge runner) - pl-predictor
===============================================================================
Τι κάνει: παρακολουθεί τον φάκελο _bridge/jobs/. Όταν εμφανιστεί εκεί ένα
αρχείο εντολής (.json), το εκτελεί στα κανονικά Windows και γράφει το
αποτέλεσμα στο _bridge/out/.

Γιατί υπάρχει: για να μη χρειάζεται ο βοηθός να πληκτρολογεί εντολές μέσω
screenshot της οθόνης, που είναι εξαιρετικά αργό. Έτσι όλα γίνονται
ακαριαία.

ΑΣΦΑΛΕΙΑ / ΔΙΑΦΑΝΕΙΑ
  * Κάθε εντολή που εκτελείται τυπώνεται εδώ στην κονσόλα, ώστε να βλέπεις
    ζωντανά τι τρέχει.
  * Κάθε εντολή καταγράφεται επίσης στο _bridge/audit.log με ώρα.
  * Κλείνοντας αυτό το παράθυρο, σταματάει αμέσως κάθε δυνατότητα
    εκτέλεσης εντολών. Τίποτα δεν μένει να τρέχει στο παρασκήνιο.
===============================================================================
"""

import os
import json
import time
import shutil
import datetime
import subprocess
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(BASE, "jobs")
OUT = os.path.join(BASE, "out")
DONE = os.path.join(BASE, "done")
AUDIT = os.path.join(BASE, "audit.log")
STATUS = os.path.join(BASE, "status.txt")

PROJECT = os.path.dirname(BASE)          # C:\pl-predictor
POLL_SECONDS = 0.4

for d in (JOBS, OUT, DONE):
    os.makedirs(d, exist_ok=True)


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def audit(msg):
    try:
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (ts(), msg))
    except Exception:
        pass


def write_atomic(path, text):
    """Γράφει πρώτα σε προσωρινό αρχείο και μετά μετονομάζει, ώστε ο
    αναγνώστης να μη διαβάσει ποτέ μισογραμμένο αρχείο."""
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)
    os.replace(tmp, path)


def run_job(job_path, jid):
    spec = json.loads(open(job_path, encoding="utf-8-sig", errors="replace").read())

    cmd = spec.get("cmd")             # λίστα, π.χ. ["git","status"]
    shell_cmd = spec.get("shell")     # ή σκέτο string για το cmd.exe
    cwd = spec.get("cwd") or PROJECT
    timeout = float(spec.get("timeout", 900))
    label = spec.get("label") or ""

    env = dict(os.environ)
    for k, v in (spec.get("env") or {}).items():
        env[str(k)] = str(v)

    shown = shell_cmd if shell_cmd else " ".join(str(c) for c in (cmd or []))
    print("-" * 70)
    print("[%s] ΕΝΤΟΛΗ: %s" % (ts(), shown))
    if label:
        print("          (%s)" % label)
    print("          φάκελος: %s" % cwd)
    audit("RUN %s | cwd=%s | %s" % (jid, cwd, shown))

    log_path = os.path.join(OUT, jid + ".log")
    started = time.time()

    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        if shell_cmd:
            p = subprocess.Popen(shell_cmd, shell=True, cwd=cwd, env=env,
                                 stdout=logf, stderr=subprocess.STDOUT)
        else:
            p = subprocess.Popen(cmd, cwd=cwd, env=env,
                                 stdout=logf, stderr=subprocess.STDOUT)

        timed_out = False
        while True:
            if p.poll() is not None:
                break
            if time.time() - started > timeout:
                timed_out = True
                try:
                    p.kill()
                except Exception:
                    pass
                break
            time.sleep(0.2)

    rc = p.returncode
    dur = round(time.time() - started, 1)
    output = open(log_path, encoding="utf-8", errors="replace").read()

    result = {
        "id": jid,
        "rc": rc,
        "timed_out": timed_out,
        "seconds": dur,
        "command": shown,
        "cwd": cwd,
        "finished_at": ts(),
        "output": output[-200000:],       # όριο ασφαλείας
        "output_truncated": len(output) > 200000,
    }
    write_atomic(os.path.join(OUT, jid + ".json"), json.dumps(result, ensure_ascii=False, indent=1))

    state = "TIMEOUT" if timed_out else ("OK" if rc == 0 else "ΣΦΑΛΜΑ rc=%s" % rc)
    print("[%s] ΤΕΛΟΣ: %s  (%ss)" % (ts(), state, dur))
    audit("END %s | %s | %ss" % (jid, state, dur))


def main():
    print("=" * 70)
    print("  ΑΓΓΕΛΙΑΦΟΡΟΣ ΕΝΕΡΓΟΣ - pl-predictor")
    print("=" * 70)
    print("  Φάκελος project : %s" % PROJECT)
    print("  Εντολές από     : %s" % JOBS)
    print("  Αποτελέσματα σε : %s" % OUT)
    print()
    print("  Κάθε εντολή που εκτελείται θα εμφανίζεται παρακάτω.")
    print("  ΓΙΑ ΝΑ ΣΤΑΜΑΤΗΣΕΙ: κλείσε αυτό το παράθυρο (ή Ctrl+C).")
    print("=" * 70)
    print()
    audit("=== BRIDGE STARTED ===")

    count = 0
    while True:
        try:
            names = sorted(n for n in os.listdir(JOBS) if n.lower().endswith(".json"))
            for name in names:
                jp = os.path.join(JOBS, name)
                jid = os.path.splitext(name)[0]

                try:
                    json.loads(open(jp, encoding="utf-8-sig", errors="replace").read())
                except Exception:
                    continue

                try:
                    run_job(jp, jid)
                except Exception:
                    err = traceback.format_exc()
                    print("[%s] ΕΣΩΤΕΡΙΚΟ ΣΦΑΛΜΑ:\n%s" % (ts(), err))
                    audit("ERROR %s | %s" % (jid, err.replace("\n", " | ")))
                    write_atomic(os.path.join(OUT, jid + ".json"),
                                 json.dumps({"id": jid, "rc": -99, "error": err},
                                            ensure_ascii=False, indent=1))
                finally:
                    count += 1
                    try:
                        shutil.move(jp, os.path.join(DONE, name))
                    except Exception:
                        try:
                            os.remove(jp)
                        except Exception:
                            pass

            write_atomic(STATUS, "alive %s | jobs=%d\n" % (ts(), count))
            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            print("\nΤερματισμός.")
            audit("=== BRIDGE STOPPED (Ctrl+C) ===")
            return
        except Exception:
            print(traceback.format_exc())
            time.sleep(2)


if __name__ == "__main__":
    main()
