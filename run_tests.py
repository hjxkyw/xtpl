#!/usr/bin/env python3
"""run_tests.py -- check the transpiler against known-good output.

Two kinds of case:

  tests/NAME.xtpl   must transpile cleanly, and the result must match
                    tests/NAME.tlpp byte for byte
  tests/NAME.dict.csv  an SX3 export to check the case's field references
                    against. Present means the case runs with --dict.
  tests/NAME.legacy    present means the case runs with --legacy.
  tests/NAME.map       present means the case runs with --map.
  tests/NAME.warn   the warnings that case is expected to print, if any.
                    Warnings are output too, so they are pinned like the rest;
                    a case with no such file must print nothing.
  errors/NAME.xtpl  must be rejected, with the message in errors/NAME.err

Run it plain to check, or with --accept to rewrite the expected files after
a change you meant to make. Read the diff before accepting.

    python3 run_tests.py
    python3 run_tests.py --accept
"""

import difflib
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).parent
TRANSPILER = ROOT / "xtpl_transpiler.py"


def transpile(source):
    """Returns (ok, generated_text, message)."""
    with tempfile.NamedTemporaryFile(suffix=".tlpp", delete=False) as tmp:
        out_path = pathlib.Path(tmp.name)
    # A case that ships a dictionary is run against it, so the field checks
    # are covered by the same golden files as everything else.
    sx3 = source.with_suffix(".dict.csv")
    options = ["--dict", str(sx3)] if sx3.exists() else []
    if source.with_suffix(".legacy").exists():
        options.append("--legacy")
    if source.with_suffix(".map").exists():
        options.append("--map")
    try:
        run = subprocess.run(
            [sys.executable, str(TRANSPILER)] + options
            + [str(source), str(out_path)],
            capture_output=True, text=True)
        produced = out_path.read_text() if out_path.exists() else ""
    finally:
        out_path.unlink(missing_ok=True)

    if run.returncode == 0:
        return True, produced, run.stderr.strip()

    # The last line of a traceback is the message worth comparing; the frames
    # above it move whenever the transpiler is edited.
    lines = [l for l in run.stderr.strip().splitlines() if l.strip()]
    return False, "", lines[-1] if lines else ""


def show_diff(name, expected, actual):
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True), actual.splitlines(keepends=True),
        fromfile=f"{name} (expected)", tofile=f"{name} (produced)")
    sys.stdout.writelines(diff)


def check_output(path, accept):
    golden = path.with_suffix(".tlpp")
    expected_warn = path.with_suffix(".warn")
    ok, produced, message = transpile(path)

    if not ok:
        print(f"FAIL  {path.name}  -- rejected: {message}")
        return False

    if accept:
        golden.write_text(produced)
        if message:
            expected_warn.write_text(message + "\n")
        else:
            expected_warn.unlink(missing_ok=True)
        print(f"ok    {path.name}  (accepted)")
        return True

    warned = expected_warn.read_text().strip() if expected_warn.exists() else ""
    if message != warned:
        print(f"FAIL  {path.name}  -- warnings changed")
        for line in difflib.unified_diff(
                warned.splitlines(keepends=True) or [],
                message.splitlines(keepends=True) or [],
                fromfile=f"{path.name} (expected warnings)",
                tofile=f"{path.name} (produced)", lineterm="\n"):
            sys.stdout.write(line if line.endswith("\n") else line + "\n")
        return False

    if not golden.exists():
        print(f"FAIL  {path.name}  -- no expected output; run with --accept")
        return False
    expected = golden.read_text()
    if expected != produced:
        print(f"FAIL  {path.name}  -- output changed")
        show_diff(path.name, expected, produced)
        return False

    print(f"ok    {path.name}")
    return True


def check_error(path, accept):
    golden = path.with_suffix(".err")
    ok, _, message = transpile(path)

    if ok:
        print(f"FAIL  {path.name}  -- expected a rejection, got clean output")
        return False

    if accept:
        golden.write_text(message + "\n")
        print(f"ok    {path.name}  (accepted)")
        return True

    if not golden.exists():
        print(f"FAIL  {path.name}  -- no expected message; run with --accept")
        return False
    expected = golden.read_text().strip()
    if expected != message:
        print(f"FAIL  {path.name}  -- message changed")
        print(f"        expected: {expected}")
        print(f"        produced: {message}")
        return False

    print(f"ok    {path.name}")
    return True



def stale_fixtures(root):
    """Fixture files this release does not know about.

    A release unpacked over an older one keeps files the release has never
    heard of -- a renamed verb, a removed feature -- and they fail for reasons
    of their own, which is confusing at exactly the wrong moment.
    """
    manifest = root / "MANIFEST.TXT"
    if not manifest.exists():
        return [], []
    listed = {line.strip() for line in manifest.read_text().splitlines()
              if line.strip() and not line.startswith("#")}
    here = {f"{folder}/{p.name}"
            for folder in ("tests", "errors")
            for p in (root / folder).glob("*.xtpl")}
    return sorted(here - listed), sorted(listed - here)


def report_stale(root):
    """True when something is out of place."""
    extra, missing = stale_fixtures(root)
    for name in extra:
        print(f"STALE {name}  -- not part of this release")
    for name in missing:
        print(f"ABSENT {name}  -- this release expects it")
    if extra or missing:
        version = "unknown"
        stamp = root / "VERSION.TXT"
        if stamp.exists():
            version = stamp.read_text().strip()
        print(f"      This is xtpl {version}. Delete tests/ and errors/ and "
              f"unpack again.")
    return bool(extra or missing)

def main():
    accept = "--accept" in sys.argv
    report_stale(ROOT)
    passed = failed = 0

    for path in sorted((ROOT / "tests").glob("*.xtpl")):
        if check_output(path, accept):
            passed += 1
        else:
            failed += 1

    error_dir = ROOT / "errors"
    if error_dir.is_dir():
        for path in sorted(error_dir.glob("*.xtpl")):
            if check_error(path, accept):
                passed += 1
            else:
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
