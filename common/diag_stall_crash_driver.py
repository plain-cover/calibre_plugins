"""Run a command repeatedly and report its outcomes as GitHub annotations.

Temporary diagnostic driver for the intermittent embedded-engine segfault:

python common/diag_stall_crash_driver.py --title TITLE --runs 30 -- COMMAND...
"""

import argparse
import re
import subprocess
import sys
import time
from collections import Counter
from typing import Dict


def _annotation(level, title, message):
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level} title={title}::{message}", flush=True)


def _signature(code, output):
    worker = re.search(r"exit code before cleanup: (-?\d+)", output)
    for marker in ("Fatal Python error: Segmentation fault", "Fatal Python error", "renderer exited"):
        if marker in output:
            detail = marker
            break
    else:
        detail = "no crash marker"
    if worker:
        detail += f"; browser worker exit {worker.group(1)}"
    return f"exit {code}: {detail}"


def main():
    split = sys.argv.index("--")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--run-timeout", type=float, default=120)
    args = parser.parse_args(sys.argv[1:split])
    command = sys.argv[split + 1 :]
    outcomes: Counter = Counter()
    first: Dict[str, str] = {}
    for index in range(1, args.runs + 1):
        started = time.monotonic()
        try:
            process = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.run_timeout, check=False
            )
            output = process.stdout.decode("utf-8", errors="replace")
            outcome = "passed" if process.returncode == 0 else _signature(process.returncode, output)
        except subprocess.TimeoutExpired as error:
            output = (error.output or b"").decode("utf-8", errors="replace")
            outcome = f"hung for {args.run_timeout:g}s"
        print(f"run {index}/{args.runs}: {outcome} ({time.monotonic() - started:.1f}s)", flush=True)
        if outcome != "passed":
            print(output, flush=True)
            first.setdefault(outcome, output)
        outcomes[outcome] += 1
    failures = args.runs - outcomes["passed"]
    summary = "\n".join(f"{count}x {outcome}" for outcome, count in outcomes.most_common())
    _annotation("error" if failures else "notice", args.title, f"{failures}/{args.runs} failed\n{summary}")
    for number, (outcome, output) in enumerate(list(first.items())[:3], 1):
        _annotation("warning", f"{args.title} - failure {number}", f"{outcome}\n...\n{output[-3000:]}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
