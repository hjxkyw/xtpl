#!/usr/bin/env python3
r"""compile_check.py -- put generated output through the Protheus compiler.

The golden tests assert that the transpiler emits what it emitted. They cannot
say whether AdvPL accepts it, and at least one bug has already been recorded
as correct because of that: a fused loop folded into a code block by
`fallback`, which is `While ... EndDo` where an expression was required.

This transpiles every fixture with --map, hands the result to a compiler
command you supply, and reads any errors back to the .xtpl line that produced
them.

    python3 compile_check.py --compiler 'advpls compile {file}'
    python3 compile_check.py --compiler '...' --only test_fusion
    python3 compile_check.py --keep          # leave build/ to look at

Write the command you already use to compile one file by hand, exactly as you
type it, with {file} where the filename goes. That is the only placeholder --
everything else stays literal:

    python compile_check.py --only test_fallback_shapes ^
      --compiler "appserver.exe -compile -files={file} -includes=C:\inc -env=MeuAmbiente"

The single-dash options there are AppServer's own and are passed through
untouched. This script's own options take two dashes, which is just Python's
convention and nothing to do with AppServer.

AppServer ends with its own verdict, and that is what is read:

    [CMDLINE] Compilation Results .: Total sources(1) Success(1) Errors(0)

Note that a CLEAN run contains the word 'Errors'. Matching the bare word
reported two files that had compiled perfectly as rejected, with a line number
that was really the length of the file. Where there is no report, the
'[ERROR]' tag is used, then the exit code -- AppServer exits 0 either way.

If it ever misreads a result, --show-output prints everything the compiler
said, banner and all.

Compiling is not running. Once a file is in the RPO, AppServer calls a
function directly:

    appserver.exe -env=zv -run=u_selftest

54_selftest is the one fixture meant to be run that way -- it checks its own
answers and prints a total.
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent
TRANSPILER = ROOT / "xtpl_transpiler.py"
RUNTIME = ROOT / "xtpl_runtime.tlpp"
BUILD = ROOT / "build"

# '// xtpl:42' as emitted by --map. The last one at or before a reported line
# is the source line that produced it.
re_marker = re.compile(r'//\s*xtpl:(\d+)\s*$')

# Compilers say where they are unhappy in more than one shape, so a few are
# tried. Each must yield the file and the line.
# 'appre0(21) Error C2051  LOCAL declaration follows executable statement' --
# the preprocessor names itself rather than the file, so the line number has
# to be taken without one.
re_bare_location = re.compile(r'\((\d+)\)\s*Error\s+C?\d*', re.IGNORECASE)

re_locations = [
    # Protheus reports 'XTPL_RUNTIME.TLPP(0) ...' -- upper case, so these are
    # all case-insensitive.
    re.compile(r'([\w./\\-]+\.tlpp)\s*[(\[:]\s*(\d+)', re.IGNORECASE),
    re.compile(r'(?:line|linha)\s+(\d+).*?([\w./\\-]+\.tlpp)', re.IGNORECASE),
]

# AppServer ends with its own verdict, which is worth more than any guess:
#
#   [CMDLINE] Compilation Results .: Total sources(1) Success(1) Errors(0)
#   [CMDLINE] Source compiled successfully. [test.tlpp]
#
# Read that when it is there. Note that the summary CONTAINS the word 'Errors'
# on a clean run -- matching the bare word reported two good files as rejected
# before this was known.
re_results = re.compile(
    r'Total\s+sources\((\d+)\)\s*Success\((\d+)\)\s*Errors\((\d+)\)',
    re.IGNORECASE)
re_compiled_ok = re.compile(r'Source compiled successfully', re.IGNORECASE)

# Only where there is no report: the tag, never the bare word.
re_failed = re.compile(r'\[\s*ERROR\s*\]', re.IGNORECASE)

# The preprocessor fails before the compiler runs, so there is no report and
# no tag -- it says so in prose instead, and AppServer still exits 0.
re_preprocessor_failed = re.compile(
    r'Precompilation of file .* with error|Exitecode equal to [1-9]|'
    r'\(\d+\)\s*Error\s+C\d+', re.IGNORECASE)


def rejected(output, code):
    """(failed, why) -- AppServer's own verdict where it gives one."""
    # Before the report, because the preprocessor runs first and its failure
    # leaves no report at all.
    if re_preprocessor_failed.search(output):
        return True, "the preprocessor rejected it"

    report = re_results.search(output)
    if report:
        errors = int(report.group(3))
        return bool(errors), f"Errors({errors}) in its own report"
    if re_compiled_ok.search(output) and not re_failed.search(output):
        return False, ""
    if re_failed.search(output):
        return True, "an [ERROR] line"
    return bool(code), f"exit code {code}"

# AppServer prints a dozen lines of banner before it says anything useful --
# version, build, SmartHeap, SSL. Dropped so the message survives.
re_noise = re.compile(
    r'^\s*(\*|\[INFO\s*\]|\[SSL\s*\]|\[WARN\s*\]|Rpo with|'
    r'\[CMDLINE\]\s*(STARTING|Using file|\*{4})|'
    # On a failure AppServer dumps its SmartHeap pools and an OS memory
    # summary -- forty lines of it, which buried the one line that mattered.
    r'-{4,}|/\*\s*={4,}|={4,}\s*\*/|'
    r'.*\.\.\.\s*[\d.]+\s*MB|'
    r'(Physical|Paging file|Virtual) memory|'
    r'\[[\d/]+ [\d:]+\] APPLICATION END)',
    re.IGNORECASE)


def interesting(text):
    """The lines worth showing: everything that is not banner."""
    return [line for line in text.splitlines()
            if line.strip() and not re_noise.match(line)]


def transpile(source, target, options):
    """Generate one file with --map on. Returns (ok, message)."""
    run = subprocess.run(
        [sys.executable, str(TRANSPILER), "--map"] + options
        + [str(source), str(target)],
        capture_output=True, text=True)
    # The last line is the message. Everything above it is warnings and the
    # traceback frames, which move whenever the transpiler is edited -- and
    # reporting the first line named a WARNING as the reason a file failed.
    lines = [l for l in run.stderr.strip().splitlines() if l.strip()]
    return run.returncode == 0, lines[-1] if lines else""


def source_lines(generated):
    """{generated line number: xtpl line number} from the --map markers."""
    mapping = {}
    last = None
    for number, text in enumerate(generated.read_text().splitlines(), 1):
        found = re_marker.search(text)
        if found:
            last = int(found.group(1))
        if last is not None:
            mapping[number] = last
    return mapping


def locate(text):
    """(file, line) pairs a compiler mentioned, in the order it mentioned them.

    Only from lines that are actually complaints. A summary naming the file
    and how many lines it has looks identical to an error location, and was
    being reported as one.
    """
    found = []
    for line in text.splitlines():
        if not re_failed.search(line):
            continue
        for pattern in re_locations:
            hit = pattern.search(line)
            if not hit:
                continue
            one, two = hit.group(1), hit.group(2)
            name, number = ((one, two) if one.lower().endswith(".tlpp")
                            else (two, one))
            found.append((pathlib.Path(name).name, int(number), line.strip()))
            break
    return found



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
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--compiler", required=True,
                        help="command to compile one file; see the header")

    parser.add_argument("--only", default="",
                        help="one fixture instead of all of them; the name "
                             "with or without .xtpl / .tlpp")
    parser.add_argument("--keep", action="store_true",
                        help="leave build/ in place afterwards")
    parser.add_argument("--show-output", action="store_true",
                        help="print everything the compiler said, banner and "
                             "all, for working out what it actually reports")
    args = parser.parse_args()

    report_stale(ROOT)

    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir()

    # The runtime first: everything else links against it, and if it does not
    # compile there is no point reading any other error. It is AdvPL already,
    # so it is copied rather than transpiled.
    shutil.copy(RUNTIME, BUILD / RUNTIME.name)
    plan = [(RUNTIME, BUILD / RUNTIME.name, None)]
    failed_to_transpile = []
    # A fixture is a pair, tests/NAME.xtpl and its expected tests/NAME.tlpp,
    # so --only names the pair. Either extension is accepted, since the name
    # on its own reads like an unfinished filename.
    wanted = pathlib.Path(args.only).stem if args.only else ""
    if args.only:
        names = [p.stem for p in (ROOT / "tests").glob("*.xtpl")]
        if wanted not in names:
            print(f"no fixture called {wanted}. Available:")
            for name in sorted(names):
                print(f"  {name}")
            return 1

    for source in sorted((ROOT / "tests").glob("*.xtpl")):
        if wanted and source.stem != wanted:
            continue
        options = []
        dictionary = source.with_suffix(".dict.csv")
        if dictionary.exists():
            options += ["--dict", str(dictionary)]
        if source.with_suffix(".legacy").exists():
            options.append("--legacy")
        target = BUILD / f"{source.stem}.tlpp"
        ok, message = transpile(source, target, options)
        if not ok:
            print(f"FAIL  {source.name}  -- did not transpile: {message}")
            # One bad fixture should not stop the other forty-eight. A stale
            # one left behind by an earlier unpacking is the usual cause.
            failed_to_transpile.append(source.name)
            continue
        plan.append((source, target, source))

    failed = 0
    for original, generated, mapped_from in plan:
        # Only {file} is substituted; anything else in the command is the
        # user's own and is passed through as typed. Absolute, because the
        # compiler may be invoked by a relative path from another directory
        # and need not resolve a relative filename the same way the shell
        # does.
        command = args.compiler.replace("{file}", str(generated.resolve()))
        run = subprocess.run(command, shell=True, capture_output=True, text=True)
        output = (run.stdout or "") + (run.stderr or "")

        # Exit code first, then the output: a compiler that prints [ERROR]
        # and exits 0 would otherwise be reported as a clean compile.
        if args.show_output:
            print(f"--- {generated.name} (exit {run.returncode}) ---")
            print(output.rstrip())
            print("---")

        failed_now, why = rejected(output, run.returncode)
        if not failed_now:
            print(f"ok    {generated.name}")
            continue

        failed += 1
        print(f"FAIL  {generated.name}  -- the compiler rejected it ({why})")

        mapping = source_lines(generated) if mapped_from else {}
        shown = False
        emitted = generated.read_text(errors="replace").splitlines()
        for line in interesting(output):
            bare = re_bare_location.search(line)
            if not bare or re_locations[0].search(line):
                continue
            number = int(bare.group(1))
            shown = True
            body = emitted[number - 1].strip() if number <= len(emitted) else ""
            print(f"        {line.strip()}")
            print(f"        {generated.name}:{number}   {body}")
            where = source_lines(generated).get(number) if mapped_from else None
            if where:
                origin = original.read_text(errors="replace").splitlines()
                wrote = origin[where - 1].strip() if where <= len(origin) else ""
                print(f"        from {original.name}:{where}   {wrote}")

        for name, number, text in locate(output):
            if name.lower() != generated.name.lower():
                continue
            shown = True
            where = mapping.get(number)
            emitted = generated.read_text().splitlines()
            body = emitted[number - 1].strip() if number <= len(emitted) else ""
            print(f"        {text}")
            print(f"        {generated.name}:{number}   {body}")
            if where:
                origin = original.read_text().splitlines()
                wrote = origin[where - 1].strip() if where <= len(origin) else ""
                print(f"        from {original.name}:{where}   {wrote}")
        if not shown:
            # Nothing matched the location patterns, so hand the output over
            # rather than swallowing it -- and the patterns want extending.
            # The banner is dropped first: it is longer than the message and
            # would otherwise be all that fits.
            body = interesting(output)
            if not body:
                print(f"        (the compiler printed nothing but its banner; "
                      f"exit code {run.returncode})")
                print(f"        command: {command}")
            for line in body[-40:]:
                print(f"        {line}")

    if not args.keep:
        shutil.rmtree(BUILD)

    print(f"\n{len(plan) - failed} compiled, {failed} failed")
    if failed_to_transpile:
        print(f"{len(failed_to_transpile)} did not transpile at all: "
              f"{', '.join(failed_to_transpile)}")
        print("  If a name there is not in this release, it is a leftover "
              "from an earlier one -- delete tests/ and unpack again.")
    return 1 if (failed or failed_to_transpile) else 0


if __name__ == "__main__":
    sys.exit(main())
