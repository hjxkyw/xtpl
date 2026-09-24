# xtpl

> **Archived project.** xtpl is deprecated and now only serves to bootstrap
> [xc](https://github.com/hjxkyw/xc), which replaces it: the same dialect,
> read by a real grammar instead of regular expressions. The tests, errors and
> runtime here are what xc is built on. The code stays here for reference.

*Versão em português: [README.md](README.md). Essa é a principal.*

An experimental source-to-source compiler: it takes a higher-level dialect of
AdvPL/TL++ and emits ordinary TL++, which compiles and runs on Protheus.

```xtpl
using alias SC6 order 1 do
  nTotal := rows("SC6", xFilial("SC6") + cNum) ;
            |> takewhile([r] r:C6_NUM == cNum)  ;
            |> map([r] r:C6_VALOR)              ;
            |> asum
end using
```

One pass over the table, no intermediate array, stopping when the order number
changes — and the work area put back as it was, including on an early
`return`.

Built to answer one question: **what modern language features could be given
to Protheus developers without changing the runtime?** The TypeScript
argument, applied to AdvPL.

> **No affiliation with TOTVS.** A personal, experimental project, written by
> an AI, never used in production. Read [DISCLAIMER.en.md](DISCLAIMER.en.md)
> first — it is short and it matters.

---

## What it does

| | |
|---|---|
| **Checking** | fields, types and sizes against an exported SX3; an alias nothing opened; argument counts; a return that exists on one path and not another; undeclared names; unused variables |
| **Scope** | `local` with block lifetime, slot reuse and escape analysis |
| **Pipelines** | `\|>` chains that become a single loop, over arrays, work areas and text files |
| **Work areas** | `using alias SA1 order 1 do ... end using`, restored at every exit |
| **Syntax** | `?:`, `?.`, `?=`, interpolation, hashes, postfix `if`/`while`, `defer`, `fallback` |
| **Existing code** | `--legacy` reads a `.prw` as it is, warning rather than refusing |

The full reference is in [`docs/language.en.md`](docs/language.en.md).

## Where it stands

- **It compiles.** All 55 fixtures and the runtime pass through the Protheus
  compiler without errors.
- **It runs.** Two fixtures execute in the environment checking each answer:
  71 pure-computation checks and 23 over a work area, a text file and the
  preprocessor. All pass.
- **It reads real code.** 121 `.prw` and `.tlpp` files from six public
  repositories pass through `--legacy`.
- **It has never run in production**, with real data, and no generated code
  has ever been deployed.

## Trying it

```sh
python run_tests.py                   # 83 fixtures, on both parsing paths
python xtpl_transpiler.py my.xtpl     # writes my.tlpp beside it
python xtpl_transpiler.py --legacy old.prw    # what is in an existing file
```

Python 3.10 or later, no required dependencies.

Optionally, [`rakulang`](https://github.com/ash/rakupp) enables the Raku
grammar path for four constructs. Without it the regex fallback is used, and
the two are held to producing identical output -- `run_tests.py` says which
path it took, since the count alone cannot tell them apart.

It is **not on PyPI**: the wheels are GitHub release assets, and the wheel
carries `librakupp.so` inside it. For Linux x86-64:

```sh
curl -sfL -O https://github.com/ash/rakupp/releases/download/v4.0.1/rakulang-0.1.0-py3-none-linux_x86_64.whl
pip install rakulang-0.1.0-py3-none-linux_x86_64.whl
```

The file name matters: pip refuses the wheel if it is renamed. For another
platform the asset list is at `https://github.com/ash/rakupp/releases` --
there are `linux_aarch64` and `macosx_arm64` builds. Building from source is
not necessary.

`fuzz_paths.py` needs both paths and refuses to run without rakulang.

**Before compiling anything**, build `xtpl_runtime.tlpp` into a custom RPO: it
defines the `u_xtpl_*` functions and the `XtplQueue` class, and nothing
generated will link without it.

### Using the AdvPL/TL++ compiler

```sh
python compile_check.py ^
  --compiler "appserver.exe -compile -files={file} -includes=C:\inc -env=MyEnvironment"
```

Transpiles every fixture with `--map`, compiles each, and reads any error back
to the `.xtpl` line that produced it. `{file}` is the only placeholder.

### Running the tests

```sh
appserver.exe -env=MyEnvironment -run=u_selftest    # 71 checks
appserver.exe -env=MyEnvironment -run=u_envtest     # 23, with its own table and file
```

## Repository

```
xtpl_transpiler.py    the transpiler
xtpl_grammar.raku     four Raku grammars, used when rakulang is present
xtpl_runtime.tlpp     support functions; compile into a custom RPO
run_tests.py          golden-file tests
compile_check.py      put the output through a real compiler
fuzz_paths.py         differential fuzzing of the two parsing paths
tests/                55 fixtures, each with its expected output and warnings
errors/               28 cases that must be rejected, with their messages
docs/language.md      the language reference (pt-BR)
docs/design.md        why it is the way it is, and what was rejected (pt-BR)
```

Code comments are in English; the documentation is in Portuguese.

## Contributing

Bug reports are welcome, especially anything that fails to compile or gives a
wrong answer.

## Licence and caveats

[MIT](LICENSE). No warranty, and the author is not liable for anything arising
from its use.

All of this was generated by an AI in conversation with the author, who
directed the design and rejected a good deal of what was proposed, but did not
write the implementation by hand. No internal TOTVS information was used.
TOTVS, Protheus, AdvPL and TL++ are trademarks of their respective owners.

The details are in [DISCLAIMER.en.md](DISCLAIMER.en.md), and they are worth
reading.
