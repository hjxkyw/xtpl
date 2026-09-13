#!/usr/bin/env python3
"""fuzz_paths.py -- the grammar path and the fallback must agree.

Four constructs are parsed by a Raku grammar when rakulang is installed and by
a regex when it is not: declarators, postfix modifiers, loop headers and the
expression tokenizer. Everything else is shared. So the two paths are the same
transpiler with four parsing steps swapped, and any input where they disagree
is a bug in one of them.

The golden tests compare the paths only over the inputs somebody thought to
write down. `return(x) if c` was such a disagreement -- correct on the regex
path, silently wrong on the grammar path -- and no fixture covered it. This
generates programs instead, runs both paths in the same process, and diffs
everything: the emitted text, the warnings, and the error if it is rejected.

    python3 fuzz_paths.py                 # 300 programs
    python3 fuzz_paths.py --runs 5000
    python3 fuzz_paths.py --seed 12345    # reproduce one report exactly
    python3 fuzz_paths.py --show          # print each program as it goes

A disagreement is printed with the seed that produced it, so it can be
replayed on its own.
"""

import argparse
import random
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import xtpl_transpiler as xtpl

GRAMMARS = ("XtplDecl", "XtplPostfix", "XtplExpr", "XtplFor")

# Everything the generator uses is declared in the signature, so a program is
# rejected for the shape it has rather than for a name nobody declared.
PARAMS = ["nA", "nB", "cA", "cB", "aA", "aB", "hA", "oA", "lA"]

SPACING = ["", " ", "  ", "\t"]
COMMENTS = ["", "", "", "  // nota", "  /* bloco */"]


def gap(rng):
    return rng.choice(SPACING)


def trail(rng):
    return rng.choice(COMMENTS)


def value(rng, depth=0):
    """An expression. Deeper ones nest, shallow ones stay simple."""
    kinds = ["num", "name", "str", "call", "hash", "member", "arith"]
    if depth < 2:
        kinds += ["chain", "interp", "elvis", "iif"]
    kind = rng.choice(kinds)

    if kind == "num":
        return str(rng.randint(0, 999))
    if kind == "name":
        return rng.choice(PARAMS)
    if kind == "str":
        return '"texto"'
    if kind == "member":
        return "oA:cCampo"
    if kind == "hash":
        return f'hA{{{rng.choice(["cA", chr(34) + "k" + chr(34)])}}}'
    if kind == "call":
        return f"minhaFunc({value(rng, depth + 1)})"
    if kind == "arith":
        return f"{value(rng, depth + 1)} + {value(rng, depth + 1)}"
    if kind == "elvis":
        return f"{value(rng, depth + 1)} ?: {value(rng, depth + 1)}"
    if kind == "iif":
        return (f"iif(lA, {value(rng, depth + 1)}, "
                f"{value(rng, depth + 1)})")
    if kind == "interp":
        # An interpolated expression cannot use the quote that delimits the
        # string it sits in, so the inner one is switched -- that rule is the
        # language's, not something to fuzz against.
        inner = value(rng, depth + 1).replace('"', "'")
        return f'"antes ${{{inner}}} depois"'
    return chain(rng, depth)


def chain(rng, depth=0):
    """A feed chain: the expression tokenizer's whole reason to exist."""
    stages = []
    for _ in range(rng.randint(1, 3)):
        stages.append(rng.choice([
            "distinct", "reverse",
            "filter([x] x > 1)", "map([x] x + 1)", "reject([x] x == 0)",
            "take(2)", "drop(1)", "takewhile([x] x > 0)",
            "asum", "amax", "count", "count([x] x > 0)",
            "anyof([x] x > 0)", "join(\", \")",
            "reduce([acc, x] acc + x, 0)", "scan([acc, x] acc + x, 0)",
            "pairwise", "sort", "chunkby([x] x)",
        ]))
    head = rng.choice(["aA", "aB", f"aA{gap(rng)}"])
    joined = f"{gap(rng)}|>{gap(rng)}".join(stages)
    return f"{head} |> {joined}"


def condition(rng):
    return rng.choice([
        "nA > 0", "lA", "cA == \"x\"", "nA > 0 .and. nB < 9",
        f"{value(rng, 2)} > 0", "nA in aA", "nA %% 3",
    ])


def statement(rng, depth):
    """One line, or a block of them."""
    kind = rng.choice(
        ["assign", "assign", "assign", "postfix", "exec", "call",
         "hashset", "block", "loop", "defer", "conout"])

    if kind == "assign":
        return [f"  {rng.choice(PARAMS[:6])}{gap(rng)}:={gap(rng)}"
                f"{value(rng)}{trail(rng)}"]
    if kind == "postfix":
        return [f"  nA := {value(rng, 1)} if {condition(rng)}{trail(rng)}"]
    if kind == "exec":
        return [f"  exec minhaFunc({value(rng, 1)}) if {condition(rng)}"]
    if kind == "call":
        return [f"  minhaFunc({value(rng, 1)}){trail(rng)}"]
    if kind == "hashset":
        return [f'  hA{{"chave"}} := {value(rng, 1)}']
    if kind == "defer":
        return [f"  defer minhaFunc({value(rng, 2)})"]
    if kind == "conout":
        return [f'  conout("valor ${{{value(rng, 2)}}}")']

    if kind == "loop":
        header = rng.choice([
            f"  for cItem in {rng.choice(['aA', 'aB'])}",
            f"  for {rng.randint(1, 5)} times",
            f"  for minhaFunc(nA) times",
            f"  for local nI := 1 to {rng.randint(1, 9)}",
        ])
        inner = [] if depth > 1 else statement(rng, depth + 1)
        return [header + trail(rng)] + ["  " + l for l in inner] + ["  next"]

    header = f"  if {condition(rng)}"
    inner = [] if depth > 1 else statement(rng, depth + 1)
    out = [header + trail(rng)] + ["  " + l for l in inner]
    if rng.random() < 0.3:
        out += ["  else"] + ["  " + l for l in (statement(rng, depth + 1))]
    return out + ["  endif"]


def program(rng):
    lines = [f"user function fz({', '.join(PARAMS)})"]

    # A prologue of declarations, where the declarator grammar earns its keep.
    for _ in range(rng.randint(1, 3)):
        parts = []
        for _ in range(rng.randint(1, 3)):
            name = f"v{rng.randint(1, 99)}"
            marks = rng.choice(["", "", f"{gap(rng)}<const>",
                                f"{gap(rng)}<contained>", " <const, contained>"])
            init = rng.choice(["", f"{gap(rng)}:={gap(rng)}{value(rng, 2)}"])
            if "const" in marks and not init:
                init = " := 0"
            parts.append(f"{name}{marks}{init}")
        lines.append(f"  local {', '.join(parts)}{trail(rng)}")

    for _ in range(rng.randint(1, 6)):
        lines += statement(rng, 0)

    lines.append(f"  return {rng.choice(PARAMS[:2])}")

    text = "\n".join(lines)
    # A continuation splits a line in half wherever a comma allows it, which
    # is where join_continuations meets everything else.
    if rng.random() < 0.25 and ", " in text:
        at = text.index(", ")
        text = text[:at + 1] + " ;\n        " + text[at + 2:]
    return text + "\n"


def run(source, use_grammar):
    """(kind, payload) -- what this path made of the program."""
    xtpl._grammars.clear()
    if not use_grammar:
        for name in GRAMMARS:
            xtpl._grammars[name] = False
    warnings = []
    real = sys.stderr

    class Catch:
        def write(self, text):
            warnings.append(text)

        def flush(self):
            pass

    sys.stderr = Catch()
    try:
        produced = xtpl.transpile(source)
        return ("ok", produced, "".join(warnings))
    except SyntaxError as complaint:
        return ("rejected", str(complaint), "".join(warnings))
    except Exception as broke:                    # noqa: BLE001
        return ("crashed", f"{type(broke).__name__}: {broke}", "".join(warnings))
    finally:
        sys.stderr = real


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=300)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    if xtpl.raku_grammar("XtplDecl", "XtplDeclActions") is None:
        print("rakulang is not importable, so there is only one path to "
              "compare. Install it first.")
        return 2

    base = args.seed if args.seed is not None else random.randrange(1 << 30)
    disagreed = crashed = 0

    for n in range(args.runs):
        seed = base + n
        source = program(random.Random(seed))
        if args.show:
            print(f"--- seed {seed} ---\n{source}")

        with_grammar = run(source, True)
        without = run(source, False)

        if with_grammar[0] == "crashed" or without[0] == "crashed":
            crashed += 1
            print(f"\nCRASH  seed {seed}")
            print(source)
            print(f"  grammar : {with_grammar[0]}: {with_grammar[1][:200]}")
            print(f"  fallback: {without[0]}: {without[1][:200]}")
            continue

        if with_grammar == without:
            continue

        disagreed += 1
        print(f"\nDISAGREE  seed {seed}")
        print(source)
        for label, result in (("grammar ", with_grammar), ("fallback", without)):
            print(f"  {label} [{result[0]}]")
            for line in result[1].splitlines()[:14]:
                print(f"      {line}")
            if result[2].strip():
                print(f"      warnings: {result[2].strip()[:160]}")

    print(f"\n{args.runs} programs, {disagreed} disagreements, {crashed} crashes")
    print(f"replay with --seed {base}")
    return 1 if (disagreed or crashed) else 0


if __name__ == "__main__":
    sys.exit(main())
