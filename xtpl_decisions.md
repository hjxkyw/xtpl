# xtpl — design log

Version 02, 2026-08-29.

Companion to `xtpl_language.md` (what the language does) and `xtpl_ch.md` (the
preprocessor header). This one records **why**, what was rejected, and what is
still open. It exists so a new conversation can pick up without relitigating
settled decisions.

---

## Files

| | |
|---|---|
| `README.md` | what this is, and what it is not |
| `DISCLAIMER.md` | independence, sources, authorship, liability |
| `xtpl_transpiler.py` | the transpiler |
| `xtpl_runtime.tlpp` | 17 functions, compile into a custom RPO |
| `xtpl.ch` | preprocessor header, the sugar half, no build step |
| `docs/language.md` | language reference (pt-BR) |
| `docs/language.en.md` | the same, in English |
| `compile_check.py` | put generated output through a real compiler |
| `fuzz_paths.py` | differential fuzzing of the two parsing paths |
| `xtpl_ch.md` | header reference |
| `tests/*.xtpl` | seven focused fixtures, each with its `.tlpp` |
| `test_kitchen_sink.xtpl` | everything at once |

Twelve fixtures: `test_reuse`, `test_pinning`, `test_defined_or`, `test_elvis`,
`test_control`, `test_array`, `test_feed`, `test_raw`, `test_const`,
`test_object`, `test_hash`, `test_operators`.

Output extension is `.tlpp`.

---

## What would carry over to a real compiler, and what would not

Written for anyone reading this as a language proposal rather than as a tool.
Much of what is here exists because a transpiler cannot change the runtime,
and would be **deleted** rather than ported.

**Would not carry over.** Slot recycling is register allocation, which a
compiler already does invisibly -- there would be no `__stk_1_0` to read, and
the origin comments that pay for it would have nothing to explain. Fusion
exists because AdvPL has no lazy sequences; a compiler with an intermediate
representation gets loop fusion from ordinary optimisation passes rather than
from a bespoke `fuse_chain`. `rows()` and `lines()` exist because there is no
iterator protocol; a compiler would add one to the language and get every
source for free, including the `items()` case held here for want of a use.
`raw` exists because the preprocessor runs after this does. `--map` exists
because the output does not look like the input.

**Would carry over, and is the actual proposal.** The checking: fields, types
and sizes against the dictionary; whether an alias is even open; argument
counts; returns that carry a value on one path and not another; block scoping
with escape analysis; `using alias` restoring at every exit. None of that
depends on being a transpiler, and none of it is reachable from the
preprocessor.

**Would carry over as design, not code.** The reasoning in this file. That
`for each` cannot honestly borrow Harbour's spelling for something narrower;
that a work-area record is not a value, so binding a name to one is
incoherent; that `distinct` and `uniq` are different algorithms needing
different names; that a guard folding statements into a code block cannot hold
a loop. Those are findings about the language, and they hold whatever the
backend is.

**What the estimate should account for**, and what building this says nothing
about: coexisting with decades of existing `.prw` and `#xtranslate` headers;
what any of it means for the RPO, linking, customer patches and per-branch
overrides; the debugger, TDS and the VM, none of which are the compiler;
writing down semantics that are currently undocumented and being right for
every existing caller. And that a real compiler gets one attempt per
construct. `distinct` changed meaning twice here in a day, and a verb was
renamed three times.

## The rule that decided everything

Every feature was judged by one question: **what does this give an AdvPL
programmer that plain AdvPL doesn't?** Applied honestly, it removed more than
it added. Removals improved the language more than additions did.

A second rule emerged later and is worth keeping: **analysis is worth building,
transformation mostly isn't.** Anything the transpiler can *check* is
distinctive value. Anything it merely *rewrites* is usually reachable from
`xtpl.ch` or not worth the dependency.

---

## Decisions, with the reasoning

### Removed, and why

| Was | Why it went |
|---|---|
| `let` | Duplicated `local` once `local` gained stack semantics |
| `gather` / `take` | Eager and lexical, so no better than `aadd`. Raku's version is load-bearing because `take` works in the *dynamic* scope — a `take` inside a called function still lands in the gather. Ours only saw the lexical block. The dynamic version was achievable with `PRIVATE` (which is dynamically scoped in AdvPL) but judged too much for the average programmer |
| `with` / `orwith` / `without` | `with` never bound the probe result, so a branch couldn't use the value it had just found. `without x do` is literally `If x == Nil`. `?:` covers first-non-Nil and *does* bind |
| Fold operators `[+]` `[*]` `[max]` `[min]` | An operator to learn where a function reads plainly, and they could not be chain stages. Named `a*` after `aScan`/`aSort`, because a plain `max` would capture AdvPL's own two-argument `Max` on every existing call | `asum` `aprod` `amax` `amin` |
| `?=>` | Chained like the feed operator but without the verbs, and did nothing without `fallback` — the `?` promised safety it never delivered |
| `local x ?= v` | A fresh block local is always Nil, so the test could never fail. Identical to `local x := v` in four lines |
| `slide` | Arrived by association with Raku, never wanted |
| `==>` then `=>` | `=>` is the preprocessor's own separator and collides with Harbour hash literals |
| Nine pipeline verbs | Removed when `=>` became generic; returned for free once the runtime existed, since they are ordinary calls |

Each raises a migration error naming its replacement.

### Kept, and why

**`given` was removed in favour of `do case with`.** `given`/`when` was an
if/elseif chain with invented vocabulary — `when eq(6)` is longer and less
readable than `Case nSub == 6`. The only thing it gave over AdvPL's own
`Do Case` was evaluating the subject once and naming it, which an optional
`with [local] x := expr` clause supplies additively: plain `Do Case` still
compiles, the conditions stay ordinary AdvPL, and the subject is an ordinary
block local that can carry `<const>`. Earlier note, kept for the reasoning:

**`given` / `when`, not `with`.** `given`/`when` is the established pairing
(Raku, Perl, Scala). `with` means "operate on this object" to anyone from
Pascal, Delphi or VB — which is most Protheus developers.

**`distinct`, not `distinctAdjacent`.** `distinct` is the SQL word, already familiar. Unix
`distinctAdjacent` and C++ `std::unique` collapse only *adjacent* duplicates, so the name
carries a wrong and dangerous second meaning.

**`|>` for feed.** Recognised as "pipe" from F#, Elixir, OCaml, R. `=>` was
taken by the preprocessor. Both the transpiler and `xtpl.ch` use `|>`.

**`?=` is an operator, never a declaration form.** Note that AdvPL's own
`Default x := v` command already does the same job — `?=` is spelling, and its
real use is a variable that branches may or may not have filled.

**`reduce` keeps its mandatory seed.** An optional seed defaulting to the first
element breaks whenever the accumulator is a different type from the elements
(counting, string building) and fails outright on an empty array.

**Block scoping and slot recycling are one feature, not two. Settled.** Block
variables are non-negotiable, and block variables without recycling are not
worth having. If every `local` inside an `if` cost a permanent function-level
slot, a long function would end up with forty declarations and programmers
would learn to hoist by hand — abandoning the discipline the feature exists to
enforce. Recycling is what makes a block local free at the point of use, and
free is what makes people use it. It also forced the escape analysis that
`<contained>` now runs on.

The escape hatch is already inside the analysis rather than beside it: anything
that provably cannot share gets private `__blk_` storage automatically, and
`<contained>` lets you demand it.

**Rejected: a runtime array (`aStk[1]`) instead of generated slot names.** Two
hard blockers, not trade-offs. `@aStk[1]` is not valid AdvPL — `@` takes a
simple variable — so `fillBuffer(@cBuffer)` would be impossible for any slot
variable. And a code block capturing `aStk[1]` captures `aStk`, the whole array
by reference, so capturing one slot effectively captures every slot and the
escape analysis loses the ability to isolate. Also slower (indexed access with
bounds checks on an interpreted VM), and worse in a debugger, where `aStk[1]`
carries no name at all while `__stk_1_0` at least gives depth and slot and has
an origin comment beside it. It would only pay against a hard locals-per-
function ceiling, which is not a constraint here.

### Design details worth not rediscovering

- **Pinning is keyed to declaration sites, not names.** Two blocks may both
  declare `aTmp`; one escaping says nothing about the other.
- **Only a code block capture stops a variable sharing a slot.** Passing a
  variable to a function is not a hazard, whatever the function does with it:
  AdvPL hands over the *object*, and rebinding our name afterwards cannot reach
  it. A code block is different — it captures the *variable* as a detached
  local. This applies to numbers and strings exactly as to arrays; it is not
  about types. `@nome` and `raw` lines pin for the same reason.
- **Superseded:** an earlier rule pinned any reference passed to a
  non-builtin function, with type inference from Hungarian prefixes, a
  builtin allowlist, and a store-is-an-escape rule for the transitive case.
  All of it was over-conservative and is gone — several hundred lines replaced
  by one substring test.
- **Generated temporaries are pooled per statement.** A chain's accumulator, a
  lifted fold, an elvis binding and the saved error block all live for exactly
  one statement, so the counter resets at every source line and the names are
  reused down the function. No analysis is needed — unlike a user variable,
  the lifetime is known by construction. Two of a kind only coexist when one
  statement needs both, such as `n := (a ?: 1) + (b ?: 2)`.
- **A pipeline is an expression, but its result may be discarded.** Run as a
  statement, the last stage emits as a plain call rather than assigning a temp
  that nothing reads — which had been leaving a bare variable on a line of its
  own.
- **A chain, a fold or an elvis nested in an expression is lifted into its own
  statement first**, and a temp left where it stood. Same move in all three
  passes. Without it the depth-zero scan cannot see them, which for `|>` used
  to be an error message rather than a design decision.
- **`fallback` is peeled from the line before any other rewrite**, so
  everything the line generates lands inside the guard.
- **Sorting copies first.** `aSort` works in place; without `AClone` it would
  reorder the caller's array, and inside a chain, the array feeding the stage.

---

## Dropped: generator coroutines

A `generator function` with `yield`, consumed with `start` and `resume`, was
fully designed and never built: the cost was in the parser, not in the
feature. It is **dropped**, not deferred -- xc reaching statement-level
parsing does not bring it back.

The case against it is the one already made under "Coroutines, revisited"
below: what is worth iterating lazily in Protheus is already resumable (a
workarea), and where laziness pays -- the pipeline -- fusion gets it at compile
time without a state machine. The full design is in the git history, in the
commit before the one that removed it.

## Rejected directions, and why

Four separate attempts to find value outside compile-time analysis. All four
came back the same way, and the pattern is the finding.

**Coroutines, revisited: generators are a different question.** The rejection
below is about *asynchronous* coroutines, and both of its arguments are about
async — yielding at points the transpiler did not create, and blocking the OS
thread. Neither applies to a generator: a generator only ever yields where
`yield` is written, and there is no scheduler to starve. So the question was
reopened on its own terms, and answered differently.

A general `yield` in AdvPL means synthesising a state machine, because there
is no `goto`: the body becomes a `Do Case` on a state field inside a `While`,
every local living across a yield becomes an object field, and nested control
flow has to be flattened. That is a real compiler transformation, and the
largest single thing anyone has proposed here. Three costs beyond the code:
the output stops resembling the input, and slot recycling has already spent
most of that budget; `defer` inside a generator becomes a promise that cannot
be kept, since AdvPL has no finalisation hook for an abandoned one; and the
escape analysis goes vacuous inside a generator, because everything crossing a
yield is pinned by construction.

What settled it is that **the things worth iterating lazily in Protheus are
already resumable**. A workarea is a coroutine with an ugly calling
convention: `DbGoTop()` is start, `!Eof()` is has-more, `DbSkip()` is advance,
and the state lives in the workarea rather than in a machine anyone has to
synthesise. There is nothing to invert.

Where laziness actually pays is the pipeline, and that is reachable at compile
time. See **Fusion** below, which buys the useful part -- no intermediate
arrays, and a `take` that stops the scan -- for a transformation the project
is already shaped to do, and which emits an ordinary `For` loop rather than a
state machine. Strictly less general than `yield`: it only works on a chain
visible whole. That covers what people write.

**Coroutines / lightweight processes.** *(This rejects coroutines for
concurrency. Generators were a separate question, answered above and then
dropped -- see "Dropped: generator coroutines".)* Erlang's and Loom's scaling comes from
the *runtime* yielding on I/O — BEAM preempts on reductions, Loom unmounts a
virtual thread when it blocks. A transpiler can build cooperative coroutines
via CPS, but they can only yield at points it created. The first `DbSeek`,
`MsExecAuto` or HTTP call blocks the OS thread and every coroutine with it — and
Protheus code is almost entirely such calls. Protheus already has real threads
(`StartJob`) and message passing (`IPCGo` / `IPCWaitEx`), which don't scale
past a few hundred but are the right tool for what ERP actually does.

**An xtpl interpreter.** Would drop everything compile-time — which is where
the value is — leaving sugar over AdvPL's `&` macro operator, at tree-walker
speed, outside the debugger. A narrow *expression evaluator* for
customer-configurable business rules is the version that could pay, since it
would give a sealed namespace and edit-time validation that `&` cannot.

**HTTP/2 and HTTP/3 in the AppServer.** Not a language problem. A reverse proxy
(Caddy, nginx) terminating h2/h3 and speaking HTTP/1.1 to Protheus is the
standard architecture, not a workaround.

**DynCall / FFI sugar.** TLPP already declares foreign signatures. xtpl would
be re-declaring platform knowledge in a second place that can drift. *If*
DynCall runs in-process — unconfirmed; the AppServer 24.3.0.1 notes read that
way but the TDN page is unverified — then a wrong signature corrupts AppServer
memory for every user, and compile-time signature checking becomes worth
building. Confirm before deciding.

---

## Open work

### A comment stopped a constant being a constant

    local v3 := 2                    ->  Local v3 := 2
    local v5 := 3  // um comentario  ->  Local v5
                                         v5 := 3  // um comentario

A literal initialiser is folded into the hoisted `Local`; anything else is
emitted as a statement. The trailing comment was being attached to the last
declarator's **value**, so `3` became `3 // um comentario` and stopped looking
like a literal. Two identical declarations came out differently, for a reason
that had nothing to do with either of them.

The comment is kept beside the value now rather than inside it, and lands on
the hoisted line. Spotted by a reader asking why one declaration in a fixture
was initialised and the one under it was not -- which is the sort of thing
only reading the output catches, since both forms are correct.

### Every release shipped so far accumulated the ones before it

`zip -r archive dir` **adds to** an existing archive. It does not replace it.
The same two temporary paths were reused for every packaging, so each release
carried its own files plus everything from every release before it.

It went unnoticed because the names never changed: each version simply
overwrote the last. Renumbering the fixtures `01_` to `53_` made it visible at
once -- the package held 132 fixtures, the 53 current ones and 53 under their
old names, plus the errors twice.

Found by being asked whether the regeneration had actually happened, and
checking the **package** rather than the working directory. The working
directory was correct the whole time.

Two things worth keeping from it. The archives are deleted before being
written now. And the manifest check, built one version earlier for exactly
this class of problem, would have caught it -- if it had been run against the
unpacked package instead of the source tree. A check only helps where it is
pointed.

### The fixtures are numbered

`01_decl_shapes` through `53_kitchen_sink`, in the order someone should meet
them: declarations and scope, then operators, control flow, comments and
`raw`, data, chains, sources, TLPP shapes and checking, and last the two files
where everything meets everything. Alphabetical order put `array` before
`decl_shapes` and `torture` in the middle, which told a reader nothing.

### Two corrections from someone who knows the language

**The type goes after the initialiser.** `Local nTotal := 0 as numeric`, not
`Local nTotal as numeric := 0`. xtpl accepts both orders in the source -- real
code writes both -- and now emits the one TLPP wants.

**`main function` is special in Protheus**, and a fixture has no business
claiming the entry point. It is still recognised as a header; it is simply not
exercised.

### Fifty-one of fifty-three

The suite through a real compiler. Everything the language does compiles:
fusion and its generated loops, `__stk_` and `__blk_` identifiers, `using
alias`, `defer`, hashes, the queue class, `fallback` and its
comma-separated code block, `raw`, `Private`, typed declarations, namespaces,
alias-scoped expressions.

Two outstanding, and neither is about what the language does.

`raw` had one more `@ ... SAY ... GET` line than the earlier fix caught -- the
fixture, not the feature.

`main function` is refused with `Regular functions are not allowed`, reported
against line 0 of the file. The suspicion is that TLPP requires a
`Main Function` to carry the **name of its source file**, which the fixture
did not. `test_main_form` exists to settle it: one function, `main function
test_main_form`, in `test_main_form.xtpl`. If it compiles, the rule is the
name; if not, `main function` is not valid here and comes out of the accepted
headers.

Worth stating plainly, since it was the whole point of the exercise: **the
five load-bearing assumptions are no longer assumptions.** `__stk_1_0` is a
valid identifier. `{|| a := 1, b := 2, b}` is a valid code block. The hoisted
`Local`s are accepted. `PCount()` compiles in the variadic `zip`. Only
`If()`'s short-circuiting remains unproven, since that is a runtime question
and nothing here has run.

### Knowing which release you are running

`VERSION.TXT` holds the number, the transpiler reads it (`--version`), and
`MANIFEST.TXT` lists every fixture the release contains. Both tools compare
what is on disk against that list before doing anything:

    STALE tests/test_uniq_maxby.xtpl  -- not part of this release
          This is xtpl 64. Delete tests/ and errors/ and unpack again.

It reports files the release has never heard of and files it expects and
cannot find. Neither is fatal -- the run continues -- but the message arrives
before the failures it explains, rather than after a confusing one.

Deliberately not done: stamping the version into generated output. It would
mean re-recording every golden on every version bump, which is churn for a
number nobody reads. The manifest catches the case that actually happened.

### A stale fixture stopped the whole run

An old `test_uniq_maxby` left behind by unpacking a new release over an older
one. `uniq` was renamed to `distinctAdjacent` several versions back, so the
chain no longer fused, so `rows()` was stranded and the file was refused.

The refusal was correct. What was wrong was everything around it: the run
**stopped** at the first fixture that would not transpile, so forty-eight
files that compile were never reached. And the reason printed was the first
line of stderr -- which was a *warning* -- followed by a Python traceback,
rather than the one line that said what happened.

`compile_check.py` reports the last line and carries on now, and names
anything that failed to transpile at the end, with a note that an unfamiliar
name is probably a leftover.

Worth remembering when unpacking: fixtures are added and removed, so a release
unpacked over an older one keeps files the release does not know about.

### The whole suite, and what five failures were made of

Forty-eight compiled, five did not, and the split is worth recording because
only one was the transpiler's fault.

**Mine, in generated code.** `Private` emitted before `Local`, since
`Private x := 0` is executable and a `Local` cannot follow one.

**Mine, in the fixtures.** Four, all written by someone who could not compile
them. A `method ... class MinhaTool` with no `class MinhaTool` block anywhere,
so AppServer read a bare `method` as a regular function. An `exit if` written
outside any loop, to test that `exit` is not a block word -- true, and
illegal. An `external STR0042` naming a constant from a message header the
file does not include, so nothing could resolve it. And
`@ 10, 5 SAY ... GET ... PICTURE`, the Clipper console form, which does not
compile as `.tlpp` at all.

That last one is the useful one. `raw` exists to hand a line to the
preprocessor, and the fixture demonstrated it with a command that no longer
exists. It now defines its **own** `#xtranslate` and uses that, so the test
depends on nothing but itself -- which is what it should have done from the
start.

**The pattern across all of them:** every fixture was written to demonstrate a
feature, by someone who knew what the feature did and could not check what the
compiler accepted. Four of five failures were about the surroundings, not the
feature. A test that has never been compiled tests the author's beliefs.

### The third: every fixture used a header Protheus refuses

    [ERROR] TEST_PRIVATE.TLPP(16) Regular functions are not allowed in code.
                                  Use USER FUNCTION or STATIC FUNCTION.

The same message the runtime got, now against a fixture -- and against most of
them, since `function name()` is what they were all written with. It reads
naturally, it is what every other language calls a function, and it is illegal
here.

Refused at transpile time now, since output that can never compile is not
worth producing. `--legacy` still lets it through, where the point is to read
a file as it is.

The three compiler findings so far are all of one kind: **the shape of a
declaration.** Bare `Function`, `Private` before `Local`, `method` without its
class. None is about what the language does -- they are about what Protheus
will accept at the top of a file, which is exactly the knowledge that cannot
be had from the inside.

### The second thing the compiler said

    appre0(21) Error C2051  LOCAL declaration follows executable statement

`Private` was emitted **before** the `Local` block. And `Private x := 0` is an
executable statement, so every `Local` after it is illegal -- the file was
rejected by the preprocessor before the compiler even saw it.

Privates go after every `Local` now. The ordering was a guess when `private`
was added, made in the same hour, and it was wrong.

Three things about AppServer's output came out of the same run. On a failure
it dumps its SmartHeap pools and an OS memory summary -- forty lines of
`... 0.12 MB. Count 1 Ok` -- which buried the one line that mattered; that is
filtered now. The preprocessor names **itself** rather than the file,
`appre0(21)`, so the line number has to be read without one. And a
preprocessor failure produces neither the `[ERROR]` tag nor a
`Compilation Results` report, and still exits 0, so it needed its own test:
`Precompilation of file ... with error`.

### The first thing the compiler said

    [ERROR] XTPL_RUNTIME.TLPP(0) Regular functions are not allowed in code.
                                 Use USER FUNCTION or STATIC FUNCTION.

The runtime was forty-six bare `Function` declarations. Protheus refuses them
outright, and `Static` was never an option -- a static function is visible
only inside its own compilation unit, so generated files elsewhere would fail
to link, which is why the file said so in a comment from the beginning.

So every runtime function is a `User Function` now, and the names carry the
`u_` prefix that goes with it: `__xtpl_map` became `u_xtpl_map`, at the
declaration and at every generated call site.

**Nothing here could have found that.** Not the golden tests, which compare
the transpiler against itself; not the fuzzer, which compares the two parsing
paths against each other; not a careful reading, because it is a fact about
the compiler and not about the code. It took thirty seconds of the real thing.

Generated files carry `#include "totvs.ch"` and `#include "tlpp-core.th"` at
the top now, and the runtime does too -- only the ones a source has not
already asked for, so a file that includes `totvs.ch` itself is not given it
twice.

### 55_envtest: the four that need an environment

`rows()`, `lines()`, `using alias` and `raw` compile and have never run,
because each needs something to work on. Rather than depend on a table from
the dictionary, the fixture **makes what it needs**: a `ZXTPL.DBF` with four
rows, a `ZXTPL.TXT` with five lines, and its own `#xtranslate` for the `raw`
tests. A `defer` erases both on every exit.

Twenty-three checks. For `rows()`: walking, filtering, counting, a predicate
stopping early, `take` cutting the walk short, `takewhile` ending at a change,
and -- the one that matters most -- that the record pointer and selected area
come back as they were. For `lines()`: reading a file, counting, filtering
blanks, `take` stopping the read, `first`, a `for` with a `loop` in the body,
a `for` with an early `return` that must still close the file, and a file that
does not exist. For `using alias`: the area restored at `end using` and at a
`return` from inside. For `raw`: one line, a block, and a declared variable
still being renamed inside one.

Three things came out of writing it, before it ran at all. `CRLF` comes from
`totvs.ch` and needs `external`, which is exactly what that is for. The table
is opened by one function and used by the others, which is exactly what
`external alias` is for. And the `raw` command needs to reach a variable from
wherever it is invoked, which is what `private` is for -- and because a
`private` is known file-wide, the `external` I first wrote alongside it was
both unnecessary and refused the assignment.

Three features earning their place in a file written to test four others.

### A range at the head of a chain

Asked how Raku's `say sum((1..999).grep: * %% (3 | 5))` would be written, the
answer was that it could not be -- and worse, that `1..999 |> filter(...)`
emitted `__fuse_src := 1..999`, which is not AdvPL, without a word.

It is the one source that walks without a collection behind it, so it is now
a source:

    nEuler := 1..999 |> filter([x] x %% 3 .or. x %% 5) |> asum

    For __fuse_i_0_0 := 1 To 999
      __fuse_v_0_0 := __fuse_i_0_0
      If (__fuse_v_0_0 % 3) == 0 .or. (__fuse_v_0_0 % 5) == 0
        __fuse_out_0_0 := __fuse_out_0_0 + __fuse_v_0_0
      EndIf
    Next

Nothing allocated, and `take` stops the walk as with any source. The spelling
is the one `in 1..100` already used.

**The counter and the element are separate variables**, which they were not in
my first version: making the counter the element saved one assignment and
broke the loop, because a `map` writes to the element and writing to a For
counter changes what it iterates.

**On the junction.** `3 | 5` was considered and rejected long before this --
`anyof`/`allof`/`noneof` say the same thing without an operator. Here it is
`.or.`, which costs one word and reads the same to someone who has never met
a junction.

### The precedence warning fired on complete calls

`zip(a, b, [x, y] len(x) == len(y)) |> count(...)` was warned about: the head
is a complete call, but the check searched its whole text for a comparison and
found the one inside the block. At depth zero only now.

A warning that fires on correct code is worse than no warning: it teaches
people to ignore the one case it exists for.

### File() was being asked once per line

    While File(__fuse_src_0_0) .And. !FT_FEof()

A filesystem call per line of the file. The check itself is needed -- a walk
over a file that never opened does not end, because FT_FEof() stays .F. -- but
asking it in the condition costs more than the read on any file worth reading.

Asked once now. The fused chain puts the whole walk inside `If File(src)`,
with the accumulator initialised ahead of it so the result exists when the
file does not. The `for x in lines(...)` form binds a flag instead: its body
is the programmer's, so an `If` around it would mean tracking a closer their
`next` does not know about.

Written in the first place as the narrowest fix to a server hang, with no
thought for what it cost per iteration.

### A block's parameter is a name for something the loop already holds

Every fused stage used to bind its parameter first:

    %l^0% := __fuse_v_0_0
    nLidas += 1
    %__um^0% := __fuse_v_0_0
    __fuse_v_0_0 := campos(%__um^0%)

The parameter is a name for the value the loop is holding in
`__fuse_v_0_0`, so it goes in directly and the binding disappears:

    nLidas += 1
    __fuse_v_0_0 := campos(__fuse_v_0_0)

A copy per stage per element, gone. In `tap([l] nConta += 1)` the binding was
worse than a copy: `l` was assigned and never read at all.

Not when the body WRITES to its parameter -- the value temp carries the
element between stages, and a stage that rebinds its own parameter must not
disturb it. One rule, applied to the single-parameter stages and to the two
names of `reduce`, `fold` and `scan` alike.

**The idea came as "pass by reference to avoid copies".** `@` is the wrong
instrument: these are assignments rather than calls, and `@` on the calls
would pin the variable and break the escape analysis that the whole slot
scheme rests on. But the observation behind it was right, and removing the
assignment beats making it cheaper.

It leaves storage declared and never mentioned, so a pass now drops any
generated name the body does not refer to, along with the `let` that marked
it. Nothing to warn about: the name was the transpiler's.

**And a blank line either side of a control structure at the outer level.** A
fused chain emits a dozen lines with a loop in the middle, and the function
read as one block of text. A comment run directly above a block belongs to it,
so the blank goes above the comment rather than between them.

### A chain cannot nest, but the verbs are ordinary functions

Asked whether the example really needed four helper functions, the answer was
no -- three of them existed only because I had reached for a chain where a
call would do.

The restriction is on the `|>` chain inside a lambda: lifting its stages out
of the block would run them before the block does, and there is no correct
place to put them. But every chain verb is also a plain function, and calling
one directly inside a lambda is fine:

    |> filter([a] len(a) == 3 .and. allof(a, ehNumero))
    |> map([a] asum(map(a, val)) / 3)

`campos`, `tresNumeros` and `media` all disappeared. What stayed is
`ehNumero`, and only because the pattern deserves a name.

That took the example from 17 lines to 13, which is what the Raku version
needs. The restriction costs nothing here; I had simply been reading it as
broader than it is, and the language reference says so no more clearly.

**And the bare-name rule was wrong.** `map(alltrim)` converts a bare name into
a block, but it was applying to EVERY argument -- so `allof(a, ehNumero)`
inside a lambda turned `a`, the lambda's own parameter, into a block too,
because lambda parameters are not in scope yet when that pass runs. Only the
last argument now, which is where the block goes for every one of these verbs.

### A chain in a declaration's initialiser produced nothing

    local aTudo := lines(cArq) |> map(alltrim)

generated

    aTudo := FT_FUse()

An initialiser has no assignment in front of it, and the chain read that as
being run for its effects: it dropped the accumulator, and the caller took the
walk's closing line as the value. It compiled, and returned whatever
`FT_FUse()` returns.

The distinction between "no prefix, so no result wanted" and "no prefix,
because the caller is placing this somewhere" already existed -- `for_value`
was added for a chain lifted out of an expression. `rewrite_value` simply
never passed it.

Found by someone asking why the example read the file twice. The two-pass
version was what I had written; the one-pass version with `tap` is what
exposed this, because it puts the chain in the declaration.

**And `map(alltrim)` now works.** A bare name where a block is expected
becomes `[x] alltrim(x)`, which is the useful half of Raku's `»`. It read as
an undeclared name before -- a poor error for a reasonable thing to write. A
name that IS a variable in scope passes through untouched, since a block held
in a variable is a legitimate argument and that is what it means.

### Def-use is not enough; the IR would have to be a control-flow graph

Asked to go for an IR, and scoped it as step one: annotate each emitted line
with the generated names it READS and the ones it WRITES, then rewrite the
peephole passes to ask the sets instead of matching the text. Output
unchanged, 89 fixtures unchanged, and a foundation to build on.

The annotation works -- it even ignores a name inside a string or a comment,
which the regexes did not. Then the first pass written on it deleted this:

    For fi_0_0 := 1 To Len(aRows)
      If ffs_0_0
        ffs_0_0 := .F.          <-- "never read further down"

That store IS read afterwards, on the next iteration. Text order is not
execution order, and a backward edge makes "below here" meaningless. Dropping
it left a 'join' with its first-element flag true for ever and no separators
at all.

**So the scoping was wrong.** Def-use answers "what does this line touch". A
dead store is a question about PATHS -- is there any path from this write to
a read -- and that needs the edges: which line can follow which. That is a
control-flow graph, and it is not something you get by annotating lines.

Which means the useful IR is not a back-end tidy-up after all. Basic blocks
need to know where a loop begins and ends, and the emitter knows that when it
writes the 'While' -- but the lines it wrote before and after have no idea.
Recovering the structure from the text afterwards is the same guessing the
peepholes do, one level up.

The honest order is: statement-level parsing, then a graph, then the passes.
The same conclusion the generator design had reached, arrived at from the
other end.

The narrow peephole stays, with a comment recording what was tried. It fires
on one shape -- a record save whose restore was just removed -- and says so.

### The spellings and 'let' are gone; a legend replaces them

The note goes on the line that declares the name:

    Local s_1_0        // um slot, dividido por aGiven, aInner, cSecond, i, nOuter
    Local b_1_nFactor  // o local de bloco 'nFactor', fixado: tem armazenamento so dele
    Local fo_0_0       // o resultado da cadeia
    Local fv_0_0       // o elemento em percurso

Once, instead of a spelling repeated on every line it appears on. Two
`#translate` rules, four transpiler passes and the per-line origin comments
all go.

The first version put this in a legend block below the declarations, which
listed every name a second time -- the duplication the legend existed to
remove, reintroduced one line lower.

**And it explains more than the spellings ever did.** `!nOuter^1^0!` said
which variable that line was; it said nothing about `fo_0_0`, `fv_0_0` or
`frc_1_0`, which had no explanation anywhere. The legend covers every
generated name, because the reader did not choose any of them.

The path here was three steps, each one the author's and each one making the
last look overbuilt. `~` made a preprocessor alias possible at all. Short
names made two of the three spellings pointless -- `s_1_aTmp` already says
`aTmp`. And this makes the third pointless too: if a name needs explaining,
explain it once rather than encoding it into every mention.

What is left is the shape I would have reached for first if I had thought
about it as a reading problem rather than a naming one.

### A chain inside a 'using alias' for the same table saved the area twice

    !usearea^1^0! := Alias()
    DbSelectArea("SX3")
    ...
      far_1_0 := Alias()          <-- again
      DbSelectArea("SX3")         <-- again

Four lines per chain that cannot change anything: the area is already
selected, and `end using` puts it back.

I had written a comment in the example explaining why this was fine -- the
chain does not know where it was called, a chain that fails to clean up would
be worse, and so on. All true, and none of it a reason to emit the lines: the
transpiler DOES know, because the enclosing `using` is on its own stack.

The RECORD is still saved per chain. The `using` restores it once, at the end
of the block, and code between two chains may rely on where the cursor was --
a walk leaves it at Eof. Only the area is redundant.

Over a DIFFERENT alias the save stays, because there the area really does
change.

### A single value at the head of a chain

    1 |> map([x] 2 * x) |> asum

generated `Len(1)` and `1[1]`. Nothing else catches it: AdvPL is dynamically
typed, so the compiler takes it happily and it fails at run time complaining
about something else.

Refused now, naming the two things it might have meant -- `{1}` for one
element, `1..99` for a sequence.

**It only catches what is visible in the source.** `local nX := 5` followed by
`nX |> map(...)` still passes, because a variable holding a scalar and one
holding an array are identical to the transpiler. Catching that needs types
xtpl does not have, and guessing from a Hungarian prefix would be wrong every
time somebody names an array badly.

Same shape as the `%%` fault earlier: an operand had to be a name, so a
literal fell down a path nobody had walked. This was the mirror -- everything
assumed the head was a name or a call.

### Names that say what a thing is, not what it will become

The `somar` example read:

    zip(aA, aB, [x, y] zip(x, y, [p, q] val(p) + val(q)))

Four single letters across two nesting levels, and nothing saying which level
was which. Rewritten:

    zip(aLinhasA, aLinhasB, [aCamposA, aCamposB]
        zip(aCamposA, aCamposB, [cCampoA, cCampoB]
            val(cCampoA) + val(cCampoB)))

    aLinhasA   every line of A, each already split -- array of arrays
    aCamposA   the fields of ONE line             -- array of strings
    cCampoA    ONE field                          -- string

The author's suggested naming had `nNumeroA` for the innermost. It is a
string: it came out of a text file and `val()` is what makes it a number. The
`c` prefix is not decoration here -- it is the one thing that explains why
`val()` is there at all. A name that says what a value will become hides the
conversion; the exercise of naming is what catches that.

**And the example now explains `zip` before using it.** It is a zipper: two
rows of teeth, joined pair by pair, with a block deciding what each pair
becomes. Two levels of pairing means two zips -- the outer matches line with
line, the inner matches field with field. That took twenty lines of comment,
which is the honest cost: a nested chain is dense, and density is not
legibility. The comment is the price of the density, not a failure of it.

### The examples' generated files were stale

`tests/` is re-recorded after every change, so those were current. The
examples were not: `euler.tlpp` and `medias.tlpp` still carried
`__fuse_out_0_0` and `__stk_1_0` from before the renaming, and `somar` had no
`.tlpp` at all. Regenerated, and `somar.tlpp` added.

They are checked in although they are generated output, because someone
reading the repository should be able to see what a `.xtpl` becomes without
running anything. That only works if they are regenerated when the transpiler
changes, which is exactly what did not happen.

**The hand-written probes are deliberately left alone.** Several use
`__stk_`/`__blk_`, which is what the generated names were called when those
probes were written and run. Rewriting them would make them claim to have
tested something they did not -- they are a record of what was executed, not
examples of the current state. `probes/README.md` says so, so nobody tidies
them later. Only `probe_control.tlpp` is generated, and that one follows.

### run_tests.py now says which path it ran

It printed `89 passed, 0 failed` whether the Raku grammars or the regex
fallback had run, because the two produce identical output -- which is the
point of the fallback and the reason the count cannot distinguish them.

That is how a partially verified result got reported as verified twice in one
day: the container lost `rakulang`, the suite kept passing, and nothing said
half the checking was gone. The line above the count says it now.

**And rakulang is not on PyPI.** The wheels are GitHub release assets and
carry `librakupp.so` inside, so there is nothing to build:

    curl -sfL -O https://github.com/ash/rakupp/releases/download/v4.0.1/rakulang-0.1.0-py3-none-linux_x86_64.whl
    pip install rakulang-0.1.0-py3-none-linux_x86_64.whl

The file name matters; pip refuses a renamed wheel. Written into both READMEs
and into what `fuzz_paths.py` prints when it finds itself with one path,
because looking for it on PyPI, finding nothing and trying to compile the C++
is the wrong turn and I took it.

### What a declaration says about a chain's head

The literal check caught `1 |> map(...)`. A variable holding a scalar reads
the same as one holding an array, so `nX |> map(...)` went through and failed
at run time -- which is where I left it, saying types were needed that xtpl
does not have.

Two of the three cases do not need types, because the declaration already
said:

    local nX := 5            an initialiser that is a scalar literal
    local cY as character    a type annotation

Both refused now, and the message says which one gave it away:

    Line 4: nX is a single value -- it was declared as 5, and a chain walks
            a collection.

The third is a parameter, which says nothing, and that one stays. Guessing
from the Hungarian prefix would be wrong every time somebody names an array
`nRows`, and a false refusal is worse than a runtime error you can read.

A runtime guard -- `If ValType(x) == "A"` around every chain -- would catch
all three and cost a check per chain for ever, to protect against a mistake
that shows up the first time the code runs. Not taken.

**`array` and `object` are deliberately not in the scalar list.** An array is
the point, and an object may well be walkable through a method xtpl knows
nothing about.

### A range with no stages did not fuse

Found while checking whether ranges accept variables. They do -- literal,
variable and expression ends all work, and bare names go straight into the
`For` header like any other source. But:

    1..999 |> asum   ->   pt_0_0 := u_xtpl_asum(1..999)

A chain with fewer than two fusable stages falls back to runtime verbs, and
`1..999` handed to one is not an expression AdvPL can evaluate. Every other
source survives that fallback because there is an array behind it; a range is
the one with nothing behind it, so it has to fuse whatever else the chain
does.

### A failed FT_FUse is not inert, and closing it was clobbering other files

The flat guard assumed an open that fails touches nothing. It does not:

    1. do arquivo bom: linha um
    2. depois de abrir o inexistente, FT_FEof() = .F.
    3. a proxima linha deveria ser 'linha dois':
    inerte: nao

A failed `FT_FUse` displaces whatever file was current, and the argument-less
`FT_FUse()` that closes the walk then closes **somebody else's**. A caller
with a file open, and a `lines()` over a path that does not exist, loses their
handle -- and the damage surfaces somewhere else entirely, which is the worst
shape a fault can have.

Both the open and the close are guarded now, in the fused chain and in
`for x in lines(...)`, including its early-exit paths:

    fok_0_0 := File(cArquivo)

    If fok_0_0
      FT_FUse(cArquivo)
      FT_FGoTop()
    EndIf

    fo_0_0 := {}

    While fok_0_0 .And. !FT_FEof()
      ...
    EndDo

    If fok_0_0
      FT_FUse()
    EndIf

The accumulator stays outside the guard: a missing file gives an empty
collection, not Nil.

**This is the shape the author proposed and I argued against twice**, on the
grounds that it cost a nesting level and gained nothing. The "gained nothing"
was an assumption about `FT_FUse` I had never tested, stated twice as though
it were known. The probe took four minutes.

### ':=' is an expression, and 'while local' got half its size back

Probed after a question about `If (fok := File(cArq))`. Five cases, all pass:
`:=` yields the value assigned, works in an `If` and a `While` condition,
chains as `a := b := 5`, and works as an argument.

The `If` case is not worth taking: the result still has to be initialised
outside any guard, so it would be the current shape plus a nesting level.

`while local` is where it pays. This:

    While .T.
      s_1_x := proximo(o)
      If !(s_1_x != nil)
        Exit
      EndIf

became this:

    While (s_1_x := proximo(o)) != nil

A loop-and-a-half -- what people write by hand for want of anything better --
replaced by an ordinary loop.

**Only when the variable's first appearance in the condition is reached
unconditionally.** Behind a `.and.` or inside an `iif` it might never be
evaluated, and the assignment is usually what advances something: a cursor, a
file, a queue. Skipping it would loop for ever. Those keep the old shape, and
`58_while_assign` pins both.

### Two warts in the generated output

**A statement that spans lines is followed by a blank.** Two chains in a row
ran together: `n := fo_0_0` sat directly above `fok_0_0 := File(cB)`, which
reads as one statement when it is two. The spacing pass put a blank after the
`EndDo`, but a chain's tail comes after that, so the seam was never separated.

**A read whose value nothing uses drops the assignment.** `count` with no test
never looks at the line, but the read must still happen for `FT_FSkip` to
advance:

    -  fv_0_0 := FT_FReadLn()
    +  FT_FReadLn()

The element temp then goes unreferenced and the pass that drops unused
generated storage removes its declaration too.

Neither was wrong; both were noise, and noise in generated output is what
makes people stop reading it.

### A source that is already a name gets no temp

    -  fs_0_0 := cArquivo
    -  fok_0_0 := File(fs_0_0)
    +  fok_0_0 := File(cArquivo)

The temp exists so an expression is evaluated once. A name is already
evaluated, and copying it only puts a second name on the reader's screen for
the same thing. It applies to every source: a file path, an array, an alias.

`lines(cDir + "a.txt")` and `concat(aA, aB) |> ...` still get one, because
those would otherwise be re-evaluated -- for the file once per `File()` and
`FT_FUse()`, for the array once per iteration of `Len()`.

### Two of the three spellings stopped earning their place

Shortening the prefixes made two of the three `#translate` rules pointless,
which was not the intention and is the better result:

    b_0_it       %it^0%        the spelling adds nothing
    b_1_nFator   %nFator^1%    nothing
    s_1_aTmp     !aTmp^1!      nothing
    s_1_0        !aTmp^1^0!    THE NAME

The spellings existed because `__stk_1_aTmp` was long and `__stk_1_0` said
nothing. With `s_1_aTmp` the name is right there, so the decoration is
punctuation around something already legible. Only a shared slot still cannot
name itself, and that one keeps its rule.

Two rules per file now, and only in files that share a slot. Most have none.

This gives up the uniformity that was the point of adding the third spelling
an hour earlier. That trade is worth it: uniformity was serving legibility,
and the short names give legibility directly.

### The generated names got shorter, and became reserved

    -  __fuse_out_0_0 := {}
    +  fo_0_0 := {}

`__fuse_out_0_0` said nothing that `fo_0_0` does not, and a fused chain puts
six of them on screen at once. `__stk_`/`__blk_` became `s_`/`b_` the same
way, and the lambda parameter the bare-name rule invents went from `__um` to
`it`, which reads: `{|b_0_it| alltrim(b_0_it)}`.

What is kept is the trailing `_<depth>_<index>`, because that is what makes
the shape impossible to type by accident.

**And now reserved explicitly.** A leading `__` was protection enough when the
names carried one; short names need the shapes declaring off-limits, or a
collision would be silent -- two different variables, one slot. One predicate
says whether a name is the transpiler's, where three separate prefix tests
used to. `fo`, `nFs_0` and `pt_x` are still perfectly good names; only
`<kind>_<digits>_<digits>` is refused.

Two faults fell out of the rename, both silent: the origin-note pattern and
the generated-name pattern still required `__`, so the shared-slot spelling
stopped running entirely and `s_1_0` went out raw. Every fixture still passed,
because the golden files had been re-recorded with the broken version.

### 121 real files through --legacy

Six public repositories from GitHub, 121 `.prw` and `.tlpp` files. All 121
pass, after seven fixes that only they found -- and every one was something no
fixture had:

- A `private` with a non-constant initialiser. Two faults in one branch, a
  `TypeError` and an `UnboundLocalError`, because no fixture had ever written
  one.
- The three newest checks firing **inside block comments**: `<br>` in a doc
  block read as an attribute, Portuguese prose read as unbalanced brackets.
  The bracket check ran before the block-comment skip, and `collect_pinned`
  never knew about them at all.
- A `local` declared over a parameter of the same name, which Protheus takes.
  Under `--legacy` that is now said rather than refused.
- **A non-breaking space** where a space belongs -- `Local cChNFE<NBSP>:=` --
  left by some editor. Protheus accepts it; `\s` does not, so the declaration
  simply could not be parsed. Normalised now, outside string literals, where
  it is data.

What it found in them: 761 undeclared names, 164 implicit `PRIVATE`s, 105
variables declared and never used, 46 assigned and never read, 31 functions
returning a value on one path and falling off the end on another, 24
declarations outside a prologue, 14 redeclarations.

The commonest undeclared names are command words -- `DEFINE`, `MSDIALOG`,
`ACTIVATE`, `PIXEL` -- which is the signal that a file is screen code and
wants `raw` rather than conversion. That is exactly what the counts were added
for, and the first time they have been pointed at anything real.

### Everything in the language has now run

    selftest: 71 ok, 0 falhas
    envtest:  23 ok, 0 falhas

`rows()`, `lines()`, `using alias` and `raw` were the last four that had only
ever compiled. `55_envtest` builds its own table through `TCLink` and
`DbCreate`, writes its own text file, defines its own `#xtranslate`, and
erases all of it on the way out.

**The open item this file has carried since it was written is closed.** It
said: *"Nothing has ever been through the Protheus compiler. Everything is
verified as 'the transpiler emits what was intended', never 'Protheus accepts
it'."* It now compiles, and it runs, and the answers are checked.

What that took, once the compiler was clean: a `%%` that ignored a literal
operand, a `u_` prefix applied twice, class methods private by default, `has`
swallowing its argument list, a PRIVATE declared in a helper that returned
before anything could read it, and a walk over a missing file that hung the
server. Six faults that only running could find, after four layers of checking
that could not.

**What remains untrue of it** is what the README says: none of this is real
code. The fixtures were written by whoever wrote the transpiler, and not one
line has run against a genuine codebase.

### `lines()` on a file that is not there hung the server

The worst failure this project has produced. `FT_FUse` on a missing file does
not raise, and `FT_FEof()` then stays `.F.`, so

    While !FT_FEof()

never ends. Not a wrong answer, not an error -- a generated loop that spins
for ever. It took a fixture asking for a file that does not exist, which is
the sort of case a demonstration never includes and a user hits in the first
week.

The walk tests `File()` as well now, in both shapes: the fused chain and the
`for x in lines(...)` form.

Worth naming what found it. Every layer here had passed: the golden tests, the
fuzzer, the compiler, and the self-test for everything that is pure
computation. It took running the environment-dependent half against a case
chosen for being ordinary rather than interesting.

**A PRIVATE lives while its declaring function is on the stack.** The
reference said a `private` is "known for the whole file", which is true of the
NAME and says nothing about the variable's lifetime -- and I then wrote a
helper that declared one and returned immediately, so it was gone before
anything could read it:

    variable does not exist CENVNOTA on ENVNOTAFOI

Declared in the function that stays up for as long as it is needed, it works.
The reference now separates the two things, because the sentence that was
there is exactly the one I misread.

**Two of the three other failures were my arithmetic, again.** `rows filtra`
expected 50 where 20 + 25 is 45, and `rows anyof acha` asked for a value
greater than 25 in a table whose largest is 25 -- a correct answer to a wrong
question. The transpiler was right in both.

**Getting the table was four probes.** The first ran twenty steps and every
one after the third failed, which was the useful outcome: `TCIsConnected()`
came back `.F.` and the warning said *Statement ignored - No connection*. A
job started with `-run=` has no database connection, and everything else was
downstream of that one fact. Guarding each step separately is what made the
root cause the third line of the output instead of the twentieth error.

`TCLink()` opens it, returning negative on failure. Then: `DbCreate` needs
`"TOPCONN"` as a third argument -- without it, it errors. `DbUseArea(.T.,
"TOPCONN", ...)` opens. `__DbZap()` empties. `DbAppend(.F.)` appends, with the
argument. `DbCommit()` writes. `TCDelFile()` drops, `TCUnlink()` disconnects,
and `DbDrop` does not exist.

`RecLock`/`MsUnlock` is not that idiom -- it belongs to the ERP layer, not to
basic database access. My probe tried it, it failed, and I nearly concluded
that plain `DbAppend()` was merely what happened to survive. It is the right
answer for a different reason than the one I had.

And a fourth thing, from the compiler rather than from writing it. I continued
a `check(...)` across two lines and forgot the `;`, which xtpl passed straight
through -- the preprocessor caught it three hundred lines later:

    appre0(440) Error C2002 Statement unterminated at end of line

**And the same mistake twice: calling a static function with `u_`.** The
compiler puts the `U_` on a `User Function`, so that one is reached as
`u_name`; a `Static Function` is called by its plain name. Getting it backwards
compiles, links, and fails only when the line runs:

    InterFunctionCall: cannot find function U_ENVDIR in AppMap

I made it in `54_selftest`, fixed it, and made it again in `55_envtest` eight
hours later. xtpl already knew how every function in the file was declared --
it reads them for the argument-count check -- so it now checks the call form
against the declaration, both ways.

**A statement whose brackets do not close cannot be a statement.** That is
checkable at the point it happens, and now is, naming the `;`. It is the
commonest typo in a language that needs an explicit continuation marker, and
it had been producing the least useful error in the set.

### It runs, and the answers are right

    selftest: 71 ok, 0 falhas

Seventy-one checks in the environment, each comparing a real answer: the
folds, every transformation, `sort` copying before it sorts, `zip` clipping to
the shortest, membership and divisibility, a fused chain against what its
stages should produce, `take` cutting the loop short, the streaming stages,
the string verbs, interpolation, hash read and write and miss, `?=` and `?:`,
`fallback` over a real runtime error, the queue's FIFO order and its empty
behaviour, a block local inside a loop, `defer` ordering.

**This is the claim changing.** It was "the transpiler emits what was
intended", then "a compiler accepts it", and it is now "the generated code
computes the right answer" -- for the part of the language that is pure
computation.

What it took, after the compiler was already clean: a `%%` that ignored a
literal operand, a `u_` prefix applied twice so forty-six runtime functions
could never be found, class methods that are private unless declared
otherwise, and `has` swallowing its argument list. Each of those would have
been a silent wrong answer or a runtime error in somebody's code.

**What still has never run** is everything needing an environment: `rows()`,
`lines()`, `using alias`, `raw`. Those compile and nothing more, and the
README says so.

### One idiom for a block variable, not two

    #translate !<name>^<num1>^<num2>! => __stk_<num1>_<num2>
    #translate !<name>^<num>!         => __stk_<num>_<name>

The body had been mixing two shapes: `!aTmp^1^0!` where storage is shared, and
a bare `__stk_2_nInner` where it is not. Both are block variables; both should
look like one.

    if nTotal > 0
      let nOuter as __stk_1_0
      !nOuter^1^0! := 1
      if nTotal > 1
        let nInner as __stk_2_nInner
        !nInner^2! := 2
      endif
    endif

Two numbers means shared storage with no honest name. One means the slot is
named after its only occupant. The rules cannot be confused, since `!x^1^0!`
never matches the one-number pattern.

And the third kind, storage that never got a slot at all:

    #translate %<name>^<num>% => __blk_<num>_<name>

A variable pinned by a capture, a `@`, a `raw` line or a `defer`, and a
lambda's parameter. **No generated name is raw in a body any more** -- every
block variable reads name-first, and the three sigils say where its storage
came from.

**The substitution was never the interesting question here.** These have
storage of their own precisely because a code block captures the VARIABLE
rather than its value, holding a live reference. If the alias broke that,
xtpl's whole escape analysis would stop being true and the damage would be
silent. So the probe built a block through the alias, assigned afterwards, and
checked the block saw the new value. It did.

**And the whole suite was re-run after every body changed shape.** Three
sigils replaced every generated name in every fixture -- three hundred-odd
occurrences -- and `54_selftest` still reported `71 ok, 0 falhas`. That the
aliasing is cosmetic at runtime is what it was supposed to be, and not
something to take on trust: the preprocessor rewrites tokens, and a rewrite
that matched one occurrence too many or too few would show up as a wrong
answer rather than as an error.

### `has` swallowed its argument list

    check("hash has", hCfg has "limite", 0, @nOk, @nBad)

became

    check("hash has", hCfg:Get("limite", 0, @nOk, @nBad, @__hash_tmp_0_0))

The key ran to the closing bracket instead of stopping at the comma -- the
same fault `in` had, in a second place, found the same way and a day apart.
Both stop at the first separator of the expression they sit in now.

**And the THashMap assumptions were right after all.** `Get(key, @out)`
returns `.T.` or `.F.` and leaves the temp untouched on a miss, which is
exactly what xtpl relies on for a missing key to read back as `Nil`. The
arity error came from `has` mangling the call, not from the signature.

`List(@aOut)` takes one by-ref parameter, returns a logical, and fills
`{{key, value}, ...}` -- column one the key, column two the value, which is
what `xtpl_pairs`, `keys` and `values` already assume. The order is not
insertion order: three keys put in as `taxa, nome, dias` came back as
`taxa, dias, nome`, which is what the reference already says to expect.

So the whole of the hash was right, and had been flagged in this file as
"inference from a worked example, needs real-run verification" since it was
written. The verification cost three probes and found nothing wrong with it --
which is a result worth having, and not one the golden tests could have
produced.

Worth keeping: my first hash probe asked `Len(oH:List())` and reported `ERRO`,
from which I concluded List did not exist. A call that does not return an
array errors under `Len` exactly as a missing method does, so the question
could not tell the two apart -- and I read the answer as the stronger claim.
A probe has to ask one thing at a time.

### The queue's methods were private

    Invalid call to a PRIVATE method named NEW on XTPLQUEUE:NEW

A method in a TLPP class is private unless declared `Public`, and calling one
from outside fails at **run** time. The class compiled cleanly in every run so
far, and `XtplQueue` had never been constructed.

Every method a caller uses is `Public Method` now; `Grow()` stays private,
since nothing outside has business calling it.

**And the self-test built its queue in the prologue**, so this one failure
stopped all sixty checks before any of them ran. It is constructed where it is
used now: a broken class should fail the queue's own checks and nothing else.
A test that stops at the first problem reports one fault per run, which is the
slowest possible way to find out what is wrong.

### The same fault twice, and a prefix applied twice

**`9 %% 3` was not translated**, for exactly the reason `5 in aNums` was not:
the operand had to be a name, and a literal was left alone with the `%%` still
in it. I fixed `in` and did not look at `%%`, which has the same shape and sat
four lines away in the same file. A fault found in one place is a question to
ask everywhere it could apply.

**`User Function u_xtpl_map` carried the prefix twice.** The compiler adds the
`U_` itself, so that declares `U_u_xtpl_map` while every generated call site
writes `u_xtpl_map`. Forty-six functions that compile, link and are never
found. The declarations carry no prefix now; the call sites keep it.

This one had survived a clean compile of all fifty-four files, because nothing
had called a runtime function yet. It would have shown up as the first line of
`54_selftest` failing and every line after it.

### `5 in aNums` was not translated at all

    check("in array", 5 in aNums, 0, @nOk, @nBad)

emitted verbatim. The `in` survived into the `.tlpp`, where it means nothing,
and the file was rejected -- the first time generated output has been refused
for something the transpiler simply failed to do.

The operand before `in` had to be a **name**. A number or a string literal was
not recognised, so the whole construct was passed through as written. Every
fixture happened to put a variable on the left, because that is what one
writes when demonstrating an operator; `5 in aNums` is what one writes when
using it.

Two things came out of the fix. `membership_span` accepts a number or a string
now, and both forms are pinned in `10_operators`. And `re_membership`, the
regex this replaced when membership moved to the node tree, was **still in the
file** -- I edited it first, re-ran, and saw no change, because nothing had
called it in weeks. Dead code that looks like the implementation costs more
than dead code that looks dead. It is gone.

Worth noting where this came from: not the compiler, and not the golden tests,
but writing a program that **uses** the language rather than demonstrating it.
The self-test found it before ever being run.

### The first thing to actually run

    appserver.exe -env=zv -run=u_probeSharedSlot
    compartilhado: 1 depois 2 depois ABC

Three names, three types, one slot -- and the values surviving each other.
Until this, every claim in this file rested on the transpiler emitting what
was intended and, latterly, on a compiler accepting it. This is the first
output produced by running any of it.

It also settles the shape below: the spellings do not merely compile, they
reach the same storage.

And `-run=` is how a function is called. That was not known here, which is why
`54_selftest` had been written and never invoked -- the one fixture built to
check its own answers, sitting in the RPO with no way to start it. It is in
the README now.

### A shared slot spells itself once per occupant

The slot-naming below handled four fifths of the cases. The rest are slots
genuinely shared by several variables, where there is no single honest name --
and those kept a number with a comment on every line saying which variable it
was that time.

The preprocessor can do better, and every part of the mechanism is the
author's:

    #translate let <name1> as <name2> =>
    #translate !<name>^<num1>^<num2>! => __stk_<num1>_<num2>

**Two rules for the whole file, whatever it contains.** The markers substitute
into the result's own name, which I had assumed was not possible -- so nothing
is enumerated and the rules do not grow with the program.

The body then reads

    if nTotal > 0
      let aTmp as __stk_1_0
      !aTmp^1^0 := {}
      aadd(!aTmp^1^0, "handed over")
    endif

    if nTotal > 0
      let cOutro as __stk_1_0
      !cOutro^1^0 := "outro tipo, mesmo armazenamento"
    endif

Two readable spellings of one piece of storage, each line saying which
variable it is that time.

**`let` marks every block-local declaration**, not only the ones in a shared
slot. A variable captured by a code block gets private `__blk_1_nFator`
storage and is no less block-scoped for it; a slot used by one variable is
named `__stk_1_aTmp` and is no less declared. The marker says the same thing
in all three cases and expands to nothing.

**The markers group at the top of their block**, so the generated code shows
the shape xtpl requires of the source -- declarations, then statements:

    if nTotal > 0
      let nTotal as __stk_1_0
      let each as __stk_2_0
      let nX as __stk_2_1
      let eachi as __stk_2_2
      !nTotal^1^0! := 0
      !each^2^0! := aNums
      For !eachi^2^2! := 1 To Len(!each^2^0!)

One cannot move: a variable declared BY a header, as in
`for local nI := 1 to 3`, where the line that opens its block is also the line
that uses it. Its marker stays immediately above the header.

Not marked: a lambda's parameter. `{|__blk_0_x| ...}` declares it in the
block's own parameter list, and fusion inlining it does not turn it into a
statement -- the name is already spelled out either way.

Three details, none of them reachable by reasoning from outside:

**`^`, not `~`.** An earlier attempt read `#translate <name>~1~0 => __stk_1_0`
and was refused -- `SSLex0105e: Invalid token, Line 14, Offset 18, ~`. `~` is
not a valid AdvPL token at all; `^` is the power operator.

**The leading `!`** stops the rule matching a genuine `a^2^3`. **The trailing
one** closes the pattern: without a terminator the last marker runs on and
swallows what follows it, which does not raise an error -- it produces a
mangled `For` header, since that is the construct with text on the right of
the spelling.

**`#translate`, not `#xtranslate`.** The two do not behave the same here, and
the reasoning would have gone the other way, since `#xtranslate` is the one
xtpl's own `raw` documentation talks about.

**Origin comments: 236 lines, then 144, now none.** The names say it.

**My part in this was mostly being wrong.** A `#define` was proposed early and
I rejected it for collision risk -- correct, and I stopped there rather than
asking what would remove the risk. Told that `~` worked, I generalised it
without compiling and shipped a file the preprocessor refuses: the exact
mistake the compiler exercise exists to prevent, made after it had already
caught seven others. I then fell back to one rule per name, fifty-seven of
them, and wrote in this file that the general form was impossible. It is two
lines.

A third, and the one worth naming. The `let` was placed at the **first use of
a spelling**, not at each declaration -- so where two sibling blocks each
declare an `aTmp` into the same slot, only the first was marked. They are
different variables that never coexist, and each is a declaration in its own
right. I had noticed this while building it and talked myself out of it as
harmless; the author noticed it in the output and did not. Declarations are
recorded where they happen now, which is both simpler and correct.

Two more faults along the way. The origin notes come in two shapes -- on
their own after `//`, or folded in parentheses into a comment the line already
had -- and reading only the first left every commented line unconverted. And
inserting the `let` as an embedded newline made one buffer entry hold two
lines, so later passes, whose patterns are anchored to a line, silently
skipped the second.

### A slot says what it holds, where it only holds one thing

The generated output is hard to read, and `__stk_1_0` is most of why. Four
fifths of recycled slots turn out to hold exactly **one** source variable, and
for those the number tells a reader nothing a name would not tell them better.

    Local __stk_1_0     ->  Local __stk_1_aTmp
    __stk_1_0 := {}  // __stk_1_0 = aTmp   ->   __stk_1_aTmp := {}

The depth stays in the name, so two variables called `aTmp` at different
depths remain distinct. The transpiler's own names lose their leading
underscores, since `__stk_1_each` reads and `__stk_1___each` does not. And the
origin comment is dropped where the name now says it -- 144 lines carry one,
down from 236.

A slot genuinely shared by several variables keeps its number. There is no
honest name for storage holding `aTmp` on one line and `cOutro` on the next,
which is exactly what the comments are for.

**Considered instead: `#define` to map generated names back to source names.**
It would work -- the preprocessor is linear, so `#define aTmp __stk_1_0` before
a block and `#undef` after it would make the body read as written. Rejected on
risk against reward. A `#define` is file-scoped, so a misplaced `#undef`
rewrites a name in some later function silently; nested blocks and early exits
make that placement delicate; and a `#define`d name can collide with a
function or field elsewhere in the file. It also buys nothing in the debugger,
which sees the substituted name either way. Naming the slot directly gets most
of the readability for none of that.

### 54_selftest: the part a compiler cannot answer

Fifty-three fixtures compile and none has ever run. `54_selftest` is one
program that exercises the runtime and the generated constructs and **checks
each answer**, printing a line per failure and a total:

    selftest: 63 ok, 0 falhas

Around sixty checks: the folds, every transformation, `sort` copying before it
sorts, `zip` clipping to the shortest, membership and divisibility, a fused
chain against what its stages should produce, `take` cutting the loop short,
the streaming stages, the string verbs, interpolation, hash read/write/miss,
`?=` and `?:`, `fallback` over a real runtime error, the queue's FIFO order
and its empty behaviour, a block local inside a loop, and `defer` ordering.

Everything in it is pure computation, deliberately. Nothing that needs a work
area, a file or a screen, because the point is a right or wrong answer rather
than an environment.

Two things it settles that nothing else could. Whether a **fused loop computes
what the chain said** -- the single largest piece of generated logic, and
until now only known to compile. And whether `defer` bodies run before the
`Return` line, which they do, in reverse order, and which therefore **changes
the returned value** when a defer touches the variable being returned. That is
worth knowing and was never written down.

One caveat about a self-test written by the same hand as the transpiler: a
check can be wrong in the same direction as the code. Three were, and were
caught only by reading the generated output -- a static function called with
the `u_` prefix that belongs to user functions, an undefined function used to
provoke an error where an out-of-range index is unambiguous, and a `defer`
expectation that had the ordering backwards.

### Everything compiles

    54 compiled, 0 failed

The runtime and all fifty-three fixtures, through AppServer. This was the open
item the whole project was blocked on, and it is closed.

**What it cost to get there.** Seven distinct faults, none of which any check
on this side could have found:

1. `Function` -- Protheus refuses a bare one; the runtime was forty-six of
   them. `Static` was never an option either, so every runtime function is a
   `User Function` and the names carry `u_`.
2. Every fixture used a bare `function` too. Refused at transpile time now.
3. `Private` emitted before `Local`, which the preprocessor rejects, since
   `Private x := 0` is an executable statement.
4. A `method ... class X` with no `class X` block in the file.
5. `exit if` written outside any loop.
6. `external STR0042` naming a constant no include supplied.
7. `@ ... SAY ... GET`, the Clipper console form, which does not compile as
   `.tlpp`.

Three were in generated code, four in fixtures. All seven were about the
**shape of a declaration or the surroundings of a feature** -- never about
what the language does. The golden tests cannot see any of it, by
construction: they compare the transpiler against itself.

**What is now known rather than assumed.** `__stk_1_0` and `__blk_0_r` are
valid identifiers. `{|| a := 1, b := 2, b}` is a valid code block, so
`fallback` is sound. Hoisting that many `Local`s per function is accepted.
`PCount()` compiles in the variadic `zip`. The `XtplQueue` class, the
`ErrorBlock` swap in `u_xtpl_safe_pipe`, the three-empty-argument `aSort`, the
`FT_` walk, `THashMap`, namespaces, alias-scoped expressions, typed
declarations -- all of it compiles.

**What is still unknown, and it is the whole of the remaining risk.**
Compiling is not working. Nothing here has ever been **executed**. Whether
`If()` short-circuits, whether `THashMap:List()` returns what `keys` and
`values` assume, whether the ring buffer in the queue is correct, whether a
fused loop computes what the chain said -- none of that is settled by a clean
compile. The next thing worth doing is running one generated function and
checking its answer.

### Superseded: the one that had to happen first

**Nothing has ever been through the Protheus compiler.** Everything is verified
as "the transpiler emits what was intended", never "Protheus accepts it". Four
assumptions are load-bearing:

- `__stk_1_0` is a valid identifier
- `{|| a := 1, b := 2, b}` is a valid code block (`fallback` over a chain)
- `If()` short-circuits its branches (`?:`)
- `PCount()` behaves as assumed in variadic `zip`
- hoisting this many `Local`s per function is acceptable

Take one real function, convert it, compile it.

### Then, in order

**1. `external` declarations — done.** `#define` constants arriving via `#include` are
invisible, so a header constant reports as undeclared. Same for `PUBLIC` /
`PRIVATE` from a caller, and bare field names without an alias. This will bite
within the first real file. Something like `external STR0001, cGlobalUser` in
the prologue.

`xtpl_dict.xtpl` exports SX3 to CSV for the next step.

**2. Check field references against the dictionary.** `SA1->A1_NMOE` when the
field is `A1_NOME` is a runtime error today, found in production. With an
exported SX3 the transpiler could reject it at compile time, check types, and
verify the alias is open in that function. **This is probably worth ten times
the syntax work** — a common, expensive bug class, invisible to both AdvPL and
the preprocessor, and exactly the shape xtpl is good at.

**3. Scoped work areas — done.** `using alias SA1 order 1 do ... end using`,
saving and restoring the area, the index order and the record pointer at every
exit including early returns. Forgetting to restore an alias is a classic
Protheus bug whose damage appears somewhere else entirely.

It shares the `defer` machinery, but is held in its own stack rather than
pushed onto `defer_stack`: a `defer` written inside the block still belongs to
the function and has to survive the block ending, while a restore has to run
when the block ends *and* at any return before that. At a return the two are
emitted in a fixed order — deferred statements first, since they may still
want the area, then the work areas, innermost block first.

**The filter is not saved.** `DbFilter()` gives back the expression as a
string, and restoring it needs the `&` macro operator to turn it into a block
again. That is a real dependency on runtime evaluation in a project whose
whole argument is compile-time checking, so it was left out rather than
smuggled in. `order` and the record cover the common half.

`rows()` does its own save and restore of area and record, which duplicates
part of this. Folding the two together is worth doing and was not: they are
reached by different paths — one is a chain head, the other a block — and
sharing would mean threading the restore list through the fusion generator.

### `for` is arrays only

Harbour's version is polymorphic — arrays, hashes, strings, objects — because
the VM implements it. A transpiler must pick a lowering at compile time with no
type information, so xtpl's walks arrays and nothing else.

Considered and rejected: a type keyword at the call site (`for x in array
aItens`). It would promise a check nobody performs, which is what `[safe]` and
`[copyref]` were removed for. A `ValType` guard was also considered and dropped
once TLPP's `try`/`catch` made the natural runtime error catchable.

### Commands and the preprocessor

`raw` exists because a `#command` / `#xtranslate` rewrites syntax, not names,
so xtpl (which runs first) would try to parse `@ 10, 5 SAY ... GET ...` as
expressions. Considered and rejected: recognising command shapes by a name list
(getting it wrong corrupts code rather than raising an error), and declaring
command words (never handles `@ 10, 5`).

Open question worth measuring: how much of the target codebase is
command-shaped. If a file is UI-heavy legacy, it may be better left as `.prw` —
xtpl output is ordinary `.tlpp` and links against `.prw` normally.

### Where the remaining value is

Analysis, not syntax. The language reads well and the last few additions were
each smaller than the one before, which is the usual signal to stop adding.
What the transpiler can *check* is what neither AdvPL nor the preprocessor can
do at all.

Next, in order:

**1. Golden-file tests — done.** `run_tests.py`. Every fixture's `.tlpp` is
committed as expected output and diffed on each run; `errors/` holds cases that
must be rejected, each with its expected message. `--accept` re-records after an
intended change. Writing it immediately caught a stale copy of the transpiler
sitting in the working directory, which every earlier "it still passes" had
silently been testing against.

**2. Field checking against the dictionary — done.** `SA1->A1_NMOE` when the
field is `A1_NOME`. Optional twice over: off unless `--dict sx3.csv` is given,
and warnings rather than errors by default, with `--dict-strict` for CI. An
unknown alias and an unknown field are reported differently, because a missing
table usually means a stale export and a missing field usually means a typo; a
close field name is suggested where there is one.

**The check runs on emitted lines, not source.** That was the decision worth
making: by emit time a field named through `rows("SA1") |> map([r] r:A1_NMOE)`
has become an ordinary `SA1->A1_NMOE`, so the chain form is covered by the
same code with no extra case. It is also the one place the alias and the field
are known together beyond doubt — which is why `rows` made this worth building
now rather than later. Before it, a bare field or a long function full of
`DbSelectArea` calls left the alias ambiguous.

Not checkable, and skipped rather than guessed at: an alias held in a variable
(`rows(cAlias)`, `(cAlias)->A1_COD`), and `M->` / `FIELD->`, which name a
memory variable and the current record rather than a table.

**Types and sizes, from the same export — done.** `X3_TIPO` catches a field
used with a literal of the wrong type, either way round; `X3_TAMANHO` catches
a string assigned to a field too small to hold it, which AdvPL truncates
silently. Both columns are optional: an export without them still gives name
checking.

**Only literals are typed, and that limit is the design.** A field used with a
variable is left alone, because inferring types across an untyped language is
exactly how a checker turns into a false-positive machine — the thing `[safe]`
and `[copyref]` were removed for. `Nil` is left alone too. The temptation to
grow this into general expression typing should be resisted; the value here is
that every warning it prints is a real bug.

The export's column names are not something to rely on, so they are found by
what the headers contain, falling back to the first two columns. That is
untested against a real SX3 export — the fixture dictionary is synthetic —
and is the first thing to check against a real one.

### Smaller, known

- Escape analysis is intra-function; nothing crosses call boundaries.
- Fourteen runtime names are intercepted, so a call to your own `take()` is
  redirected. Collision surfaces at link time, not silently.
- `xtpl.ch` rules are untested against the Protheus preprocessor; two are
  marked RISKY (`fallback` and `?:` both begin with a match marker).
- Cross (`X`) was considered and deferred — product grids are a real use, but
  it should wait for a file that wants it.

---

## The list

Kept here so it survives the conversation that produced it. Ordered by
value per effort, not by appeal.

### Done

**Is this alias open?** A field reference against an alias nothing in the
function opened. It only became checkable once `using alias` and `rows()`
existed — those are what let a function state which areas it opens; before
them the alias was always ambiguous. `DbSelectArea` and `ChkFile` count too,
and `external alias SA1` declares the caller-opened case, which is the same
promise `external` already makes about a name.

Reported **once per alias, not per use**: a function naming SA1 twenty times
has one problem, not twenty. The first version reported all twenty, which
would have taught anyone to ignore the warning. Off under `--legacy`, where an
alias opened by the caller is the norm rather than the exception.

**A value on one path and nothing on another.** `Return nTotal` in the `If`
and a bare `Return` at the end, or no return at the end at all — the caller
gets `Nil` and finds out somewhere else and later. Both shapes are reported
against the line that returns nothing, naming the line that returns a value.

**Line mapping, `--map`.** Every emitted line carries `// xtpl:42`. This is
the second of the two weaknesses measured against TypeScript — the output does
not look like the input — and the only one of the two that is fixable. The
marker goes on *every* generated line rather than the first of each group,
because scanning upwards for the nearest one is exactly the work it exists to
remove.

**`join` as a fusable terminal.** It was excluded structurally rather than
because joining is hard: a terminal was recognised by taking *no* arguments,
and `join` takes a separator. With it excluded the fusable run was one stage,
which is below the threshold for fusing at all — so `map |> join` fell back
entirely and warned, on code that was perfectly reasonable.

It now writes the string directly. A flag marks the first element rather than
testing the accumulator for emptiness, because a legitimately empty first
element would otherwise lose its separator. `join` with no argument joins with
nothing, matching the runtime version, and skips the flag.

**`reduce` and `fold` as fusable terminals — and why not an annotation.**
The question was whether a `<fusable>` marker could let a user's own function
fuse. It cannot, for two reasons worth keeping. Fusing needs the *body*, not
permission: `map` fuses because the transpiler knows what map means and can
write the loop, whereas `myHelper(aData)` would have to be read, its loop
found, and its per-element part identified — inlining across a function
boundary, which nothing else here does. And an unverifiable annotation is
exactly what `[safe]` and `[copyref]` were removed for: if the function is not
element-wise, the generated loop is silently wrong, which is worse than the
warning it replaced.

The generalisation that does work was already in the language. `reduce(a,
block, seed)` is what the four named folds have in common — a seed and a
per-element step — and the block is right there to read, so it needs no trust.
`asum`, `aprod`, `amax`, `amin` and `join` stay as sugar, but they are no
longer the only way to fuse a fold. `fold` is the seedless form, starting from
the first element.

Still out of reach, and left warning: a stage that expands one element into
several, or carries state between elements. Those genuinely need the body
inlined.

**A queue, and the bug it found.** Needed no transpiler work at all -- a class
in the runtime plus a `queue()` verb to build one -- which is the argument for
it having been the only data structure worth adding. A ring buffer, because
the gap was never "arrays cannot grow" but "taking from the front is O(n)".

**It immediately exposed something wider.** The runtime-verb substitution
matched a bare name followed by '(' anywhere on the line, so `oFila:Count()`
became `oFila:u_xtpl_count()`. That was never about queues: any object with a
`Count`, `Map`, `First`, `Take` or `Sort` method had its calls rewritten into
calls on methods that do not exist -- and FWModel objects have several of
those. The substitution now refuses to match after ':' or '->'.

Two things about that are worth keeping. It had been there since the runtime
verbs existed and no fixture caught it, because no fixture called a method
named like a verb. And it was found by adding the least ambitious thing on the
list.

**`scan`, `expand`, `tap`, `pairwise` -- and the refactor `expand` forced.**
Every fused stage until now opened either nothing or an `If`, so the body
tracked how many blocks were open as an integer. `expand` opens a `For`, and a
count cannot say what closes. `closers` is now a list of the words each open
block ends with. The change was behaviour-neutral and verified against the
fixtures before anything used it.

Doing it caught something worth remembering about blanket edits: replacing
`depth += 1` everywhere also hit four ordinary delimiter counters in
`extract_parens`, `elvis_operand_span` and `interpolate`, which have nothing
to do with fusion and promptly failed with `closers is not defined`. Ten
fixtures said so immediately.

`pairwise` is the awkward one. Building a pair needs the previous element
while `prev` is already being set up for the next pass, and the nested-block
body has no room *after* the rest of the chain -- so both the old value and
the had-one-yet flag are read into temps before either is overwritten.

**`distinctAdjacent`, and the naming that took three tries.** The log records `distinct`
being chosen over `distinctAdjacent` because "Unix `distinctAdjacent` and C++ `std::unique` collapse
only *adjacent* duplicates, so the name carries a wrong and dangerous second
meaning." That reasoning was right, and it was about a global operation. The
adjacent operation now exists, and `distinctAdjacent` is the name it has everywhere else —
so both names now mean exactly what they mean outside xtpl. `distinct` is the
SQL one, O(n²), compares against everything kept so far, blocks fusion;
`distinctAdjacent` is the Unix one, O(n), compares against the previous element, fuses.

It shipped briefly as `uniq`, which is what Unix and `std::unique` call it —
and the old log entry had already explained why that name is dangerous here.
`distinctFromSorted` was considered and rejected for a better reason: it names
a **precondition the operator does not have**. Collapsing runs in a
chronological sequence, to find where a value changed, is a perfectly good use
on input that was never sorted — and a name promising sortedness would also
invite the assumption that something checks it, which is the fault `[safe]`
and `[copyref]` were removed for, moved into a name.

`distinctAdjacent` states the mechanism rather than a requirement, and pairs
with `distinct` so the relationship is visible at a glance.

**Two bugs came out of the rename itself**, both worth knowing. A
word-boundary rename missed `u_xtpl_uniq`, because `_` is a word character.
And `_FUSE_STEPS` briefly held `distinctAdjacent` in camel case, which never
matched anything: `read_stage` lowercases every verb name, which is why
`sortby` and every other entry in those tuples is already lowercase. The
user-facing spelling and the internal one are not the same string.

**`maxby` / `minby`.** Nearly free once `first` existed: the same terminal
shape, carrying the best seen instead of leaving at the first match. A flag
rather than a Nil test, because an element may legitimately be Nil.

**`first` / `count`.** Both replace `filter(...)` plus a look at the result,
which builds an array to answer a question that needs none. The distinction
worth recording is which of them may follow `rows()` without a `map`: `count`
reads the element and needs nothing made from it, while `first` hands the
element *back*, and a work-area record is not a value. That split now has a
name -- `_FUSE_ELEMENTWISE_OK` -- rather than being the predicate set by
accident.

`count` with no condition counts what reaches it. That is not a synonym for
`len()`: it is how to size a walk over a source that has no length until it
has been read.

**`chunkby`.** A terminal rather than a step: a chunk only exists once the key
changes, so it cannot emit one element per element the way the fused step loop
requires. Downstream stages carry on from the array of chunks. A flag marks
whether a group is open rather than comparing the key against Nil, because Nil
is a legitimate key.

**It found a real bug in the work-area rewriting.** `read_body` was rewriting
`r:FIELD` into a field reference for *every* stage of a chain over `rows()`,
but after a `map` the element is whatever the map produced -- an ordinary
value. So `rows(...) |> map([r] {r:C6_NUM, ...}) |> chunkby([x] x[1])` was
refused, on the grounds that `x` was being used for something other than
naming a field, when `x` was not a record at all. The rewrite is now scoped to
the stages before the first map. Nothing existing exercised this, because no
fixture had a block after a map over a work area.

**`takewhile` / `dropwhile`.** `takewhile` stops at the first failure and
looks no further, which is what separates it from `filter`. Over an ordered
work area that is the point: once the key changes the rest is known not to
match. `dropwhile` needs a flag rather than a test, because after the leading
run an element that would have matched must still pass.

**Building it exposed a limitation worth naming: `rows()` always does
`DbGoTop`.** So `takewhile` alone finds a keyed group only when that group is
at the front of the table, which is not the case the feature was argued for.
The two compose into a correct general form — `dropwhile` to reach the group,
`takewhile` to end it — and that never reads past the group, but it reaches it
by scanning rather than by seeking.

**Closed with an optional second argument: `rows(alias, key)` seeks rather
than going to the top.** Three shapes were weighed — a positional argument, a
`seek` clause, and `rows()` inside a `using alias` block silently honouring
the position already set. The third was rejected as too implicit: the same
`rows("SC6")` would mean different things depending on where it sat. The
second reads better but buys new syntax where there is currently a function
call.

The index order deliberately stays out of it. A seek needs one, but
`using alias SC6 order 1 do` already sets orders and each construct then does
one thing:

    using alias SC6 order 1 do
      aItens := rows("SC6", xFilial("SC6") + cNum) |> takewhile(...)
    end using

A seek that finds nothing lands on Eof, so the walk produces nothing, which is
the right answer and needs no test of its own.

Worth noting how this arrived: it came from building `takewhile` and finding
the headline example did not work, not from reading a catalogue of operators.
That is better evidence than anything else queued.

**`keys` / `values` / `pairs`.** The largest gap in the language, and one of
the cheapest fixes on the list: `for` walks arrays, so a hash was invisible to
the entire pipeline. These return arrays rather than being sources like `rows`
and `lines` — a hash is in memory and finite, so there is nothing to stream —
and that is why nothing else had to change. `for`, the chain, every verb and
interpolation composed with them the moment they existed.

**One inference is load-bearing and should be checked against a real run.**
`THashMap:List()` fills an array with one row per entry, and the documentation
does not say which column is which. A worked example concatenates
`aList[3][1]` onto a string, which only compiles if column 1 is character, and
in that example every key is a string while the values include `.T.`, a date
and a number — so column 1 is the key. `keys` and `values` both derive from
`u_xtpl_pairs`, so if that reading is wrong there is exactly one function to
correct.

Confirmed while looking it up: THashMap keys may be numeric, character or
date, values may be any type, and the class also has `Del(key)`, which nothing
in xtpl uses yet. The order `List()` returns is not documented, so nothing
here sorts — `|> sort` is there for anyone who needs it.

**Stack, queue, list.** Considered, mostly rejected. AdvPL arrays are already
dynamic, so a stack is `AAdd` plus `ATail` plus `aSize` and a class would be a
thin wrapper. The exception is a **queue**: removing from the front means
`ADel` then `aSize`, which is O(n) per pop and awkward enough to get wrong, so
a ring buffer would be genuinely better than what is available. A linked list
has no case at all — its advantage is cheap insertion, and dynamic arrays with
no iterator invalidation already give that.

**`each` dropped from `for each`.** The three for-forms are told apart by
their shape -- ':=' for the counted form, a trailing 'times', a standalone
'in' -- so the grammar never needed the word and neither does a reader. The
argument for keeping it was Harbour familiarity, and that argument turned out
to cut the other way: Harbour's FOR EACH walks hashes, strings and objects,
deciding at runtime, while this one walks arrays and the two sources. Keeping
the spelling advertised a compatibility that is not there, which is the same
fault as `lines()` looking like a function call. `for each` now raises a
migration error rather than reporting 'each' as an undeclared variable.

**`for x in lines(f)`.** Refused for `rows()` and right for `lines()`,
and the difference is the whole reason: a work-area record is not a value, so
the element name there was a fiction; a line is a string, so it binds
ordinarily and the body needs no rewriting.

Three exit routes had to work, and the design follows from the middle one.
`FT_FSkip()` goes straight after the read rather than at the foot of the loop,
because the body is the programmer's and may contain a `Loop` — which over a
skip at the foot would never advance the file and would hang. Closing the file
is an exit-path job like restoring a work area, so it rides on the same stack
and an early `return` closes it too.

The fused chain form keeps its skip at the foot, which is safe there because
that body is generated and provably contains no `Loop` — filters became nested
`If`s for exactly this reason when `rows()` was built.

**Binary files: not supported, and not detected.** `FT_FReadLn` splits on line
endings, and AdvPL strings are bytes rather than decoded text, so a binary
file does not fail the way it would in Python or Raku — it is silently cut at
every 0x0A and truncated by whatever the FT_ family's line limit is. That puts
xtpl in the C camp rather than the Python one: no distinction, no error. A
`bytes(file)` source over `FOpen`/`FRead` would be the honest answer if a use
case appears; documented as a limitation rather than guessed at for now.

**`anyof` / `allof` / `noneof`.** Fusable predicate terminals that leave the
loop at the first answer. They read the element rather than a value made from
it, so a chain over `rows()` needs no `map` before one — and the work-area
walk itself stops, which is the case that matters: asking whether any customer
has a negative balance should not read the rest of SA1.

**`--check`.** Parse and report, write nothing; the output path becomes
optional. Warnings still go to stderr and the exit status stays 0, so
`--dict-strict` beside it is what makes a dictionary warning fail a build.
Small, as expected.

Also settled here: **errors say `Line`, warnings say `line`**, throughout. The
prefix is added where the report is made rather than written into each
message, so the two cannot drift apart again.

Two more trailing-comment bugs turned up while building these, both the same
old shape — an end-of-line anchor that cannot see past the masked token.
`external alias SB1  // note` read the comment as one of the names, and a bare
`Return  // note` counted the comment as the value returned, so a function
with that shape looked consistent when it was not. That makes five appearances
of this bug in different constructs. Anything that parses to the end of a line
should peel first; there is now a `peel_comment` for exactly that, and the
remaining question is why it still has to be remembered rather than being
structural.


**`lines(file)` as a chain source.** The same protocol as `rows()`, over text,
lowering to the `FT_FUse` / `FT_FReadLn` / `FT_FSkip` idiom that Protheus
already uses. The file is never held in memory, so a `take` genuinely stops
the read. It cost almost nothing: the fusion generator already took a source
skeleton, so this was a third one beside the array and the work area.

Two decisions worth recording. **A bare `lines(f)` with no stages is a chain**
— every line of the file — rather than an error. That covers the useful half
of `slurp` without loading the file into one string, and it fell out of the
same code, which is an argument for building `lines` before `slurp` rather
than beside it. And **a source used anywhere but the head of a chain is
refused**: there is no function of that name to link against, so without the
check it was emitted as a call and failed at the AdvPL compiler with nothing
to say why. The names `rows` and `lines` are consequently taken, like the
runtime verbs.

### Done earlier this round

**Strings, and interpolation.** The runtime carries only what AdvPL lacks —
`split`, `join`, `starts`, `ends`, `contains`. `Upper`, `AllTrim`, `PadL` and
the rest already take their subject first, so they compose with `|>` as they
stand, and adding them to `runtime_verbs` would have shadowed the originals on
every existing call. Interpolation runs before every other pass, so the
literal is an expression by the time anything else looks at it.

**Argument counts** against signatures in the same file. Only too many is
reported: a missing parameter arrives as `Nil` and code relies on it, an extra
one cannot be reached. No external data, no inference, no false positives.

### Next

Nothing ranked. The streaming list is finished; what follows is held for a
reason, not queued.

**The source category is named — done.** You called `lines(f)` artificial, and
the diagnosis was that the language had a category it did not name: `rows` and
`lines` are legal at the head of a chain and as a `for` source, refused
everywhere else, and are not values — but they are *spelled* like function
calls, so the syntax promises a value and then withdraws it. Each section
re-explained its own restrictions, and nothing said the two were the same kind
of thing.

The reference now has a `Sources` section stating the rule once, and the
per-source sections stopped repeating it. It also says why the restriction
exists rather than leaving it to look arbitrary: laziness here is a
compile-time property, so there is no object carrying an iterator to hold on
to. Raku's `lines` can be bound to a variable because its runtime has an
iterator protocol; AdvPL has none, and building one would mean an `Eval` per
element per stage.

No code changed. The behaviour was already this; only the explanation was
missing, which is why it was the one deferred item worth doing without new
evidence.

**`items(oThing)` — a source protocol, waiting for a use case.** Protheus
repeats one shape in three places and has no word for it: `DbGoTop` /
`!Eof()` / `DbSkip` for a work area, `FT_FGoTop` / `!FT_FEof()` / `FT_FSkip`
for a text file, and the same as the first for a TCQuery result. `rows` and
`lines` are two hard-coded skeletons for it. `items(oThing)` would be a fourth
that walks any TLPP object with `GoTop`, `Eof`, `Value` and `Skip`, so a
paginated REST reader or an XML walker could join the pipeline and get `take`,
`chunkby` and `count` for free.

**This is not the `<fusable>` annotation trap.** That was refused because
fusing a user function needs its *body*, not permission. This needs no body at
all: it emits a fixed sequence of four calls. The only thing trusted is that
the methods exist, which is the promise `external` already makes about a name,
and it fails at link time rather than silently.

**Held because there is no object to walk yet.** `rows` and `lines` each came
from a request; this came from noticing a pattern. Building it now would mean
inventing the use case. The signal to build it is finding yourself writing
`While !oThing:Eof()` around a class of your own — and by then the third
skeleton already exists, so a fourth is mechanical.

Named `items` after `cursor` was rejected: in Protheus a cursor is
specifically a TCQuery result set, so the name would read as "the thing you
already have" rather than "anything". `items` keeps the family as plural nouns
saying what you get -- `rows`, `lines`, `items` -- at the cost of a collision
with domain vocabulary, since order items are also items. `walk` was the other
candidate and says what is done rather than what is got, which breaks the
pattern the other two set.

### Dropped

**`spurt` / `slurp`.** `lines(f)` with no stages already reads every line of a
file, which is what anyone would reach `slurp` for, and `MemoRead` /
`MemoWrite` cover the rest. What was left was a rename, which fails this
project's own test.

**`==>` for chains, and leftward chains.** Considered and dropped. `|>` stays.

**Junctions.** Explored properly and dropped: without autothreading a junction
only means anything in comparison position, and every useful form already has
a spelling in xtpl.

| junction | what already exists |
|---|---|
| `x == any(a, b, c)` | `x in {a, b, c}` |
| `x == none(...)` | `!(x in ...)` |
| `x > all(aList)` | `x > amax(aList)` |
| `x > any(aList)` | `x > amin(aList)` |
| `x < all(aList)` | `x < amin(aList)` |
| `x == one(...)` | nothing, and no use for it |

The relational row was the one expected to be the real gap, and it is not:
`> all` *is* `> amax`, and `amax(aLimites)` reads more plainly than a form
that requires knowing `>` distributes over a junction. Net addition: `one()`,
which nobody wants.

**What the exploration did turn up** is that there was no way to ask whether
*any* element matches without building a filtered array and taking its length
— reading the whole collection to answer a question usually settled by the
first element. That gap is real and is what `anyof` / `allof` / `noneof`
fill; they are not junctions, they are the LINQ/Python shape, named to avoid
colliding with anything AdvPL already has.

**Index order checking against SIX.** The machinery would have been nearly
copy-paste from the SX3 work, which is what made it look attractive. Dropped
because the trade runs the wrong way: it catches one narrow thing — an order
number out of range — while the expensive bug, seeking on the key of a
different order, needs the key expression parsed and matched against the seek
expression, which is the inference-across-an-untyped-language that field
*type* checking was deliberately kept away from. On top of that, Protheus code
creates temporary indexes at runtime constantly (`IndRegua`, `DbCreateIndex`)
and none of them are in SIX, so every one would be flagged; and customers add
indexes freely, so an export from one environment is wrong in another. Cheap
to build, low value, high false-positive rate — the opposite of the trade that
made field checking worth having.

**C++-style lambdas, in both shapes.** The inline form was dropped on
legibility: a statement body wedged into a chain reads worse than the helper
it replaces, and what it bought was only not naming that helper and not
threading captures through its signature by hand.

Reworked as a class -- a functor, an object with a `Run` method -- it stopped
being about inline-ness and became about state: multiple entry points, and a
mutable field an object owns rather than a detached local sitting in the
enclosing function. A validator that counts what it rejected cannot be written
as a code block, because the count has nowhere to live.

The design was pleasingly small: no new syntax at all, just an
`u_xtpl_apply(bWhat, xArg)` in the runtime that checks `ValType` and calls
`:Run()` for an object or `Eval` for a block, with every verb going through
it. Zero transpiler changes, the same shape as the queue.

Dropped anyway, on the cost of the check: a `ValType` and an extra call per
element, on every use of every verb, paid by everyone who only ever passes a
plain block. `Run` would also have been a magic method name with nothing
enforcing it. For the stateless case `{|p| helper(p, nTeto)}` is one line and
needs none of this, and no case with real state has come up.

**Decimal as a first-class type.** Dropped as too large. The tension that
killed it is worth keeping, because the idea will come back: making a type
first-class normally means tracking types, and this project has avoided that
everywhere — the hash subscript `h{key}` was chosen precisely so no tracking
was needed. An attribute-declared version (`local nSaldo <decimal>`) needs no
inference and is the only shape worth reconsidering, but the cost is not the
declaration, it is everything downstream: comparisons, `cValToChar`, passing
to a function that expects a number, and what happens when a decimal meets a
plain number in one expression.


## What this is

A hobby project exploring what current AI tooling can build, and a sketch of
modern features TOTVS could put in the compiler one day — the TypeScript
argument, made against AdvPL.

Measured against TypeScript, xtpl is strong where TypeScript was strongest
(the checking *is* the product) and weak on the two things that actually drove
TypeScript's adoption: it is **not a superset** and the **output does not look like the input**
(`__stk_1_0` is not what the developer wrote).

`--legacy` closes the first of those: the prologue rule and mandatory
declarations become warnings, so an existing `.prw` compiles and can be
tightened a rule at a time — TypeScript's `strict: false` path.

**Built on a wrong belief, and corrected later.** The first version assumed
AdvPL accepts a `Local` inside a block and treats it as function-scoped, as
Clipper and Harbour do. On that basis `--legacy` forced every declaration to
function scope, reasoning that block lifetime would change what existing code
*means*.

AdvPL rejects it outright -- both a `Local` inside a block and a `Local` after
the first statement. So there is no existing code with either shape to be
compatible with, block scoping is **purely additive**, and forcing function
scope under `--legacy` was not a compatibility measure but a silent removal of
the feature from code that was not legacy at all. It is gone.

**And the second rule turned out to be narrower still.** In AdvPL, *reading* an
undeclared name is an error -- so that check is not an xtpl restriction either.
*Writing* to one is legal and creates a `PRIVATE`: an anti-pattern, but
something existing code does. That single case is the whole of what stops xtpl
accepting a `.prw`.

So the documentation went from "two rules stop xtpl being a superset" to one
rule, to one *case* of one rule. Each correction came from the author knowing
the language, and each made the claim smaller and truer.

It also changed the behaviour. A write to an undeclared name is now reported
once, where it happens, as what it is -- `'cX' is not declared, so this creates
a PRIVATE` -- and reads after it are silent, because by then the variable
exists. Before, one implicit `PRIVATE` was counted as three undeclared uses,
which both overstated the problem and misdescribed it. A read with no write
before it is still reported, since AdvPL would reject that too.

The initialiser still stays where it was written when a declaration is outside
a prologue, but the reason is simpler than the one first given: folding it
into the hoisted `Local` would run it at function entry, which is a different
program.

**How it was caught:** the author said so, after the feature had shipped and
been documented twice. Nothing in the transpiler could have found it -- it is
a fact about the target language, and every test agreed with the wrong version
because the tests only ever compare xtpl against itself. It belongs in the
same list as the `fallback` bug that a golden file recorded as correct.

An undeclared name is left as written and deliberately **not** registered:
declaring it would add a `Local` the source never had, and the whole promise
of legacy mode is that the file still compiles to what it compiled to.

**The counts are the point as much as the warnings.** The log's open question
was how much of the target codebase is command-shaped, and it could not be
answered because a real `.prw` died on the first undeclared name. Now a few
hundred files can be run through and the distribution read off: `SAY`, `GET`
and `PICTURE` at the top of the undeclared list mean a file wants `raw`, not
conversion. That is real information about the target, and the nearest thing
to a compiler run that does not need the compiler.

Slot recycling is the one feature that does not generalise to a real compiler:
register allocation there would be invisible, with no `__stk_1_0` to read. It
earns its place in a transpiler for a reason a compiler would not need.

## The parser is moving to a Raku grammar

The line scanner is regex-and-masking: it works, but every construct added a
guard, and several bugs this session came from one pattern seeing text another
had already rewritten.

`rakulang` — a pip-installable package embedding Raku++ as a shared library —
makes a real grammar available *without* a rewrite. Grammars compile once
(~8 ms) and parse at roughly 15,000 lines/sec, returning the AST as ordinary
Python lists and dicts.

**Done: declarations, postfix modifiers, feed chains.** `xtpl_grammar.raku`
holds three grammars, each used when `rakulang` is importable and falling back
to the old scanner when it is not. Both paths produce identical output on every
fixture, which is the point of having golden tests before starting.

**The tokenizer is shared, and is not about feeds.** `XtplExpr` reports
where the structure is — brackets, commas, code blocks, feeds — and returns a
flat node list; the transpiler walks it. Splitting the work there keeps the
pipeline error messages in Python, where the line number lives, and left the
per-stage parse (`re_pipe_segment` plus `extract_parens`) untouched, so no
error message moved. That regex is clean, not guard code; it can go later if
there is a reason.

What it deleted: three hand-rolled delimiter counters (`split_feed`,
`find_feed_at_depth`, and the brace loop of the leftover check), the reuse of
`elvis_operand_span` to find a nested chain's bounds, and — twice — a guard on
the character *before* a `|`, which existed so the `||` opening a
zero-argument code block could not be read as a feed. The grammar consumes a
block's parameter list with the brace that opens it, so the question never
arises. The same capture distinguishes `{|o| o:nValue}` from the array literal
`{1, 2}`, which the line scanner could not do at all.

**Found by the migration: a chain inside a code block was silently wrong.**
`map(aNums, [x] x |> triple)` emitted `{triple(|__blk_0_x| __blk_0_x)}` — a
call with a block delimiter for an argument. The scanner could not see the
containing block, so it lifted the stage out regardless; where the block sat
before the feed the lift produced garbage that then failed name resolution,
reporting `'triple' is not declared`, which blames the wrong thing. It is now
refused: a block body runs later, so there is no correct place to lift a stage
to. `errors/feed_in_block` pins it. Lowering it *inside* the block, as
comma-separated expressions the way `fallback` already does, is possible and
was not built — no use case yet.

**Done: hashes, on the same node list.** `h{key}` and the hash literal
needed no grammar of their own — the tokenizer already answers both of their
questions. Gone: a second brace-depth loop that scanned for the matching `}`,
and the one-character lookahead that told a subscript from a code block by
checking whether `{` was followed by `|`. A subscript is now simply a headless
brace group whose left neighbour ends in an identifier. `hash_literal_pairs`
lost its use of `split_top_level` and `find_top_level` the same way: a `=>`
inside a nested group is that group's, so a `=>` in a text node is by
construction at the top level.

Worth saying plainly: **this one found no bug.** Output is byte-identical to
the previous transpiler on every fixture and on a stress file covering nested
subscripts, subscripts inside code blocks, and both literal forms. It removed
guard code and nothing else — which is the ordinary case, and the feed
migration turning up a real bug was the exception.

That the hash pass needed no new grammar is the finding worth carrying
forward: the remaining constructs should be checked against the node list
before anyone writes a grammar for them.

**Done: loop headers.** `XtplFor` covers `for x[, i] in <source>` and
`for <count> times`, with ordered alternation putting the more specific form
first. Plain `for x := ...` stays where it was: it is a different shape, and
folding it in would buy ordering it already has.

**A comment on a loop header used to break it.** Masking turns a comment into
one token, and both loop regexes were anchored to the end of the line, so

    for 3 times                    // repeat three times

was not recognised as a loop at all and `times` fell through to the
undeclared-name check — `'times' is not declared`, which blames the wrong
thing entirely. `for` had the milder version: the comment was swallowed
into the source expression and re-emitted on the binding line.

**Credit where it is due: the grammar did not fix this.** Both paths were
broken identically and both are fixed by `peel_comment`, six lines that split
a trailing comment off before either the grammar or the regex sees the line.
It has to live in Python because only the transpiler knows whether a trailing
masked token is a comment or a string literal — the grammar sees the same
token either way. The lesson is the ordinary one for this project: the bug was
found by writing a loop header with a comment on it and reading the output,
not by moving the construct to a grammar. `tests/test_loop_comment` pins it.

Worth recording for the next grammar: `token` is `:ratchet`, so a trailing
non-greedy run cannot extend to satisfy something in the *parent* rule. The
first `for` draft matched one character of its source and stopped. Either
terminate the run inside its own token, as `fortimes` does with the word
`times`, or bound it with a lookahead.

### Fusion

A chain was one call per stage, each walking its input and building a new
array. Three stages over 500,000 rows is three loops and two arrays thrown
away, to produce perhaps ten values. Element-wise stages are now emitted as
the body of a single loop.

Fusable: `map`, `filter`, `reject`, `take`, `drop`, and `asum` / `aprod` /
`amax` / `amin` as the last stage, where no array is built at all. `take`
becomes an `Exit`, which is the part that changes complexity rather than just
constants -- the loop stops instead of computing everything and discarding the
rest.

**Only the leading run is fused, and the rest carries on normally.** `sort`
cannot yield anything before it has seen the last element and `distinct` has
to remember what it has seen, so `filter |> map |> sort` fuses the first two
and sorts the array they built. All-or-nothing fusion would have given up on
most real chains.

**A single stage is left as an ordinary call.** One stage is one loop either
way, so fusing would only make the output longer and cost the runtime call its
readability.

**The warning was asked for, and is deliberately narrow.** It fires only when
the chain was using the element-wise verbs and something stopped them; a chain
of ordinary functions was never a candidate and saying so on each one would be
noise. Getting that rule right took two attempts -- the first version stayed
silent when the fusable run was too short to fuse, which is exactly the case
worth reporting.

**`take` reads at most one element past its limit.** It is tested on arrival,
so the loop notices on element n+1. Against walking the rest of the source
that is nothing, and it keeps the lowering to four lines. Worth revisiting if
a source is ever a workarea, where one extra element is one extra `DbSkip`.

### `rows` — the source protocol

`rows(alias)` at the head of a chain fuses into a work-area walk. This is
where fusion stops being an optimisation: a chain over an array of 500,000
rows is merely wasteful, but `SA1` cannot be loaded into an array at all, so
the alternative was writing the `While !Eof()` loop by hand.

**The body is emitted as nested `If`s rather than early `Loop`s.** This was
forced: with `Loop`, a filter would skip the `DbSkip()` and hang the loop.
Nesting removes the hazard by construction and reads better, so the array
skeleton was changed to match rather than keeping two shapes.

**The element is the record, not a value.** There is no object to bind, so
`r:A1_COD` is compiled to a field reference and any other use of the name is
refused — `filter([r] isOk(r))` has nothing to pass. A chain also has to
`map` before a terminal, since there is nothing else to collect. Both are the
kind of thing only a transpiler can check, which is where this project keeps
concluding the value is.

**A literal alias is written out**, because `SA1->A1_COD` is what gets read in
a debugger and in review; anything else is bound once and reached through
`(cAlias)->`. The literal goes back into the output as the masked token it
arrived as — rebuilt with real quotes it was rescanned as code and the alias
inside it reported as an undeclared variable, which cost a debugging round.

**Area and record pointer are restored.** Not the order or the filter.
`using alias ... do` now covers the order as well; the two save-and-restore
paths remain separate, which is noted there as worth folding together.

Still open: `for oRow in rows("SA1")`. The chain form was done first
because a lambda body is a bounded piece of text to rewrite, while a `for
each` body is arbitrary statements and the `r:A1_COD` rewrite would have to
reach all of them. Worth doing, but it is a different mechanism, not a
variation on this one.

### Warnings are pinned now

Adding the fusion warning broke two fixtures, because `run_tests.py` treated
any output on stderr as an unexpected warning -- which meant the existing
unused-variable warnings were not checked at all, only asserted to be absent.
A `tests/NAME.warn` file now holds what a case is expected to print, diffed
like the rest; a case with no such file must print nothing. Warnings are
output too.

### Masking and function flushing

Two more from probing the machinery rather than the constructs.

**`/* ... */` was not handled at all.** `mask_literals` works one line at a
time and knew only `//`, so a block comment's body was scanned as code and
reported whatever it happened to contain as an undeclared name. Block comments
are ordinary AdvPL, so this would have hit the first real file.

They are folded into the `//` form by `fold_block_comments`, before anything
else reads the source — including the `external` and `#define` scans, which
had been reading the raw text and would have picked up either from inside a
comment. Folding rather than teaching each pass a second comment form keeps
the change to one function. A block ending part-way through a line has its
text moved to the end, since `//` runs to the end; nothing is discarded and
the line count is preserved, so every line number still points where it did.

Checked and correct already: `/*` inside a string, `//` inside a string, a
string containing the other quote style, and an unterminated string (masked to
end of line and left for the AdvPL compiler, which is the right place for it).

**A function with no statements dropped its defers.** `flush_function` looks
for the last line that is code and not a comment, to insert before any
trailing comment. With declarations hoisted, a body of declarations and
defers has no such line, and the defers were dropped silently:

    user function cleanupOnly()
      local nCount := 0
      defer closeCursor()

They are the function's exit path whether or not anything else is there, so
they now become the body. The normal case is byte-identical.

### Line continuation, the last piece of machinery

`join_continuations` rewrites the line set before any pass runs, so it is the
one thing every construct depends on. Continued declarations, chains, hash
reads and `fallback` all came through correctly. One case did not.

**A comment after the `;` stopped the line continuing at all.** The test was
`masked.rstrip().endswith(";")`, and a masked comment is a token sitting after
the `;`, so

    aBig := aNums ;                     // keep only the big ones
            |> filter([x] x > 10)

did not join. Two silent failures followed: the `;` was emitted as written,
and the orphaned second line was transpiled as a statement of its own — which
the feed pass turned into `u_xtpl_filter(, {|x| ...})`, composing the stage
with an **empty first argument** rather than refusing it. The `;` is looked
for past the comment now, and the comment moves to the end of the joined
statement, since once the lines are one there is nowhere else for it to sit.

The empty head is fixed separately, because it is worth refusing however it is
reached: `'|>' has nothing on its left`. That the chain pass would compose an
empty argument at all is the kind of gap only a malformed input finds, which
is the argument for probing the machinery rather than the constructs.

Also tightened on the way: the `;` is now located in the masked text rather
than by `rfind` on the raw line, so a semicolon inside a string can never be
mistaken for the continuation marker.

### `fuzz_paths.py`

The golden tests compare the grammar path against the regex one only over
inputs somebody thought to write down. `return(x) if c` was a disagreement
between them -- correct on the regex path, silently wrong on the grammar path
-- and it took a human reading the grammar to notice, because no fixture
covered it.

`fuzz_paths.py` generates programs instead. It runs both paths in the same
process, by clearing the grammar cache for one and pre-poisoning it for the
other, and diffs everything: the emitted text, the warnings, and the error
message if the program is rejected. Every report carries the seed that
produced it, so a disagreement replays on its own.

**Two bugs on the first run of 150 programs**, both in the regex path, both
about declarator lists.

`local v1 <const, contained> := 0` -- an attribute list holds commas of its
own, and `<` and `>` are not delimiters to `split_top_level`, so the list was
cut in half and `contained` became a declarator of its own with a `Local` to
match. Attribute groups are set aside before the split now and put back after,
which is the same move masking makes for literals.

`local a := 1, b  // nota` -- a list ending on a bare name has nowhere to
absorb a trailing comment. The regex swallowed it into the value, which worked
only while the last declarator had one; the grammar, anchored to the end of
the line since the review round, refused the whole list. Both peel it first
now, and it is put back on the declarator it was written against.

Note what those have in common with the review findings and unlike the
torture findings: they are **divergences**, not faults. Each path was
self-consistent. Only running both and comparing finds them, and only over
inputs nobody chose.

1600 programs across four seeds after the fixes, with no disagreement.
`tests/test_decl_shapes` keeps both shapes.

Worth being clear about the limit: the generator only emits constructs it
knows about, so it exercises the four grammars and the shared code they feed,
not the whole language. It found nothing that a single path gets wrong on its
own -- by construction it cannot.

### `compile_check.py`

`run_tests.py` asserts that the transpiler emits what it emitted. Nothing has
ever asked whether AdvPL accepts it, and the `fallback`-over-a-fused-chain bug
below is what that costs: invalid output, recorded as the expected result, and
green for as long as nobody looked.

`compile_check.py` transpiles every fixture with `--map`, hands each file to a
compiler command, and reads any error back to the `.xtpl` line that produced
it:

    FAIL  test_comments.tlpp
            test_comments.tlpp(23) Error: syntax error near 'While'
            test_comments.tlpp:23   nSafe := u_xtpl_safe_pipe(...)  // xtpl:15
            from test_comments.xtpl:15   nSafe := riskyCall(1) fallback 0

That is what `--map` was built for, and until now nothing used it.

**The compiler command is a parameter**, since it differs by installation:

    appserver.exe -compile -files={file} -includes={includes} -env={env}

Three things about the real output were guessed wrong and fixed once it was
seen. Protheus reports `XTPL_RUNTIME.TLPP(0)` in **upper case**, and the
patterns required lower, so the filename and the line number came back swapped
and the script crashed converting a filename to an integer. It can report an
error and **still exit 0**, so the output is read as well as the exit code.
And the header never explained that `{file}` was a placeholder at all.

One error line from a real compiler found all three.

A fourth came from a **successful** run. Failure was taken from the exit code
or from the word 'error' appearing anywhere in the output -- and AppServer
finishes a clean compile with

    [CMDLINE] Compilation Results .: Total sources(1) Success(1) Errors(0)

so two files that had compiled perfectly were reported as rejected, with a
line number that was really the length of the file. AppServer's own report is
read now, since it states the answer outright; the `[ERROR]` tag and then the
exit code are the fallbacks, and a location is only taken from a line carrying
the tag. AppServer exits 0 whether it succeeded or not, so the exit code alone
was never going to work.

The lesson is the one the golden files taught, from the other side: a check
that has never seen a real success does not know what one looks like either.

The runtime is compiled first and copied rather than transpiled, since
everything else links against it and an error there makes the rest
meaningless.

### A guard costs the fusion, and now says so

`fallback` folds the line into a code block as comma-separated expressions,
and a fused loop is not one -- so a guarded chain silently went back to the
runtime calls, a pass and an array more than it had been. Nothing said so, and
nothing in the source shows it.

It warns now, and the message names the better shape: guard the part that can
fail, leave the chain outside it. Which immediately exposed that the better
shape did not work -- `(riskyCall(2) fallback {}) |> filter(...)` reported
`'fallback' is not declared`, because the guard is peeled at the top of a line
and this one is inside brackets. A nested guard is lifted into its own
statement now, so the advice and the implementation agree.

**And `?=` inside an expression reached the output verbatim.** It is a
statement -- `name ?= value` on a line of its own -- and nothing rewrites it
anywhere else, so `(f() ?= {}) |> tap(...)` emitted `?=` into the `.tlpp`,
which is not AdvPL. Refused now, pointing at `?:`, which is what that shape
wants and which fuses. The check runs at any depth, since the case that
reached the output was nested.

All three came from one question about whether a guard could go on a chain.

### A chain run for its effects now fuses

Asked whether a `for` loop over an array could be a chain instead. It could --
but the effects-only form was *worse* than the loop it replaced: fusion
refused without a result to build, so `filter |> tap` became two runtime calls
and an intermediate array.

The reasoning behind the refusal was sound for the case it was written for --
do not build an array nobody reads -- and wrong here, because a `tap` chain is
the point rather than a discarded value. A chain with no assignment now fuses
with **no accumulator at all**, which is exactly the loop somebody would have
written by hand. A chain of ordinary functions still does not fuse; it never
was a candidate.

Also corrected on the spot: the first version refused a walk run for effects,
`rows("SA1") |> tap(...)`, on the grounds that it had to produce something. It
does not -- walking a table to print each row is an ordinary thing to want,
and it produces the `While !Eof()` loop directly.

### A second real file: PRIVATE and native code blocks

Forty lines of dialog code, and it broke on two things that are in most real
Protheus files.

**AdvPL's own code block declared nothing.** `{|u| ... }` -- the parameter
between the bars was an undeclared name, and so was every use of it in the
body. xtpl's `[x] body` form registered its alias; the native form, which is
what actual code is written in, did not.

**There was no `private`.** The file is built on one: `oMGet` is created in
the dialog function and reached from a button's callback, which is what
dynamic scope is for. xtpl could not express the correct version of that code
-- `external` promises a name exists but refuses assignment, and a `local`
would be invisible to the callback. The only honest conversion was `--legacy`,
which is to say none.

`private` now declares one, and because a PRIVATE is dynamically scoped the
name is known for the **whole file**, readable and assignable. It carries no
attributes and recycles no slot: nothing can promise what happens to a name
visible to the entire call stack. And it is never reported unused, since
existing for what it calls is the point.

That closes a hole worth naming: xtpl refuses an implicit PRIVATE as an
anti-pattern, and until now offered nothing to replace it with. The refusal
was telling people to write worse code, or to give up.

The file also had two variables assigned and never read -- the buttons
register themselves with their parent, so the names do nothing.

### A real file, and six more gaps

An actual Protheus tool -- 250 lines, a class with methods, a namespace, JSON
schemas, an embedded SQL query, work-area walks -- found six things at once.
None was subtle, and none had come up in seventy-five fixtures.

**It could not be read at all.** ISO-8859-1 with CRLF, and the transpiler
assumed UTF-8: a raw `UnicodeDecodeError` on a real file. The encoding and the
line ending are both detected and carried back to the output now. Writing
UTF-8 from a latin-1 source would corrupt every accented string on the way to
a compiler that is not expecting it.

**Protheus.doc blocks were being destroyed.** `/*/{Protheus.doc} ... /*/` was
folded into `//` like any other block comment, which silently breaks the
format other tools read. A block comment taking up whole lines is now kept
exactly as written, and its position is noted so the checks that ask what the
last statement was do not mistake a doc block for code.

**The type can go on either side of the initialiser.** `x as numeric := 1` was
handled; `x := 1 as numeric`, which is what the file writes, was not -- the
value simply swallowed `as numeric`.

**Parameters carry types too.** `method process(jPayLoad as json)` left the
parameter unregistered, so every use of it was an undeclared name.

**`ALIAS->( expression )` evaluates in that work area**, so a bare name inside
it is one of that alias's fields. `SC9->(C9_CLIENTE+C9_LOJA)` was reported as
undeclared. This is the case the reference said had no answer; it has one.

**And it found a real bug in the file.** `cAliasA := oQuery:OpenAlias()` is
never declared anywhere -- an implicit `PRIVATE`, the anti-pattern. That is
the one thing xtpl checks that AdvPL does not, and the first real file it saw
had an instance of it.

After the six, the file transpiles with no warnings and the output differs
from the input only in case, hoisting and comment spacing.

**Twice now a real program has been worth more than the whole fixture set.**
Both times for the same reason: the fixtures and the transpiler come from the
same source, and share its blind spots.

### Three gaps found by one real program

A short, real TLPP program -- twenty lines -- turned up three things xtpl did
not know, and the first was the worst failure mode the project has produced.

**An unrecognised function header silently copies the whole file.**
`main function` was not in the pattern. Nothing was recognised as a function,
so nothing was ever *inside* one, so every line fell out untouched: no error,
no warning, output identical to input. The transpiler appeared to work.
`main` is in the pattern now, and a file where no header is recognised says
so.

**`as object` was not understood.** TLPP's type annotation is ordinary in real
code and xtpl refused the declaration outright. It is parsed on both paths now
and emitted back on the hoisted `Local`. Nothing is done with it -- no
checking, no inference -- but nobody is made to drop it either. A block local
on a recycled slot cannot keep it, since the slot is shared.

**A namespaced call was read as undeclared names.**
`totvs.tools.Foo.Bar():New()` -- the middle segments already passed as
dot-flanked, like `.And.`, but the root did not. Told apart from `nA.And.nB`,
which is lexically identical, by the whole dotted path ending in a call.

Fixing the second exposed a fourth: `collect_pinned` rebuilt a declarator by
concatenating the name and the rest without the space between them, which had
never mattered while the rest always began with `:=`.

**What this says about the fixtures.** Seventy-two of them, written by the
person who wrote the transpiler, and one real program found three gaps in
twenty lines. Every fixture used a header form xtpl already knew, because it
was written to test something else. The lesson is not that more fixtures were
needed -- it is that they all came from the same source.

### A deliberate bug hunt, and what it says about the tests

Written as adversarial combinations rather than demonstrations: nested walks,
chains inside arguments and conditions, comments and continuations cutting
constructs in half, a source inside a defer. Six bugs, all in code that had
passed every fixture. `tests/test_torture` keeps the shapes.

**A string literal inside an interpolated expression.** `"${h{'moeda'}}"` --
interpolation inserted the expression *unmasked*, so quotes inside it were
exposed to the identifier scan and `moeda` was reported undeclared. The
expression is re-masked on the way out now.

**A source chain nested in an expression never fused.** `fuse_chain` refused
without an assignment prefix, on the reasoning that a discarded chain has no
result worth building -- but the nested-lift path also has no prefix, and
*its* result is wanted. `rows()` therefore survived unfused and was reported
as stranded. The two cases are now told apart by `for_value`.

**A multi-line defer body lost its nesting.** The splice stripped each line
and re-indented them all to one column, which was invisible while a defer was
a single call and became a flattened loop once a defer could hold one.

**A chain inside a stage's own argument was refused.** The nested lift only
ran when there was no chain at *this* level, so
`a |> take(len(b |> distinct))` left the inner one in place. The lift is
unconditional now.

**`fallback` over a fused chain emitted invalid AdvPL, and a golden file
agreed with it.** The guard folds everything the line generates into one code
block as comma-separated expressions; a fused loop is `While`/`EndDo`, which
is not an expression. The output contained `For ... Next` inside `{|| ... }`
and had been recorded as the expected result. **This is the clearest example
yet of what the golden files cannot do**: they assert that the transpiler
emits what it emitted, never that AdvPL accepts it. Under a guard an array
chain now goes unfused, back to the runtime calls it used before fusion
existed, and a source -- which has no unfused form -- is refused with a
reason. `wrap_fallback` also checks its own steps for statement keywords now,
so a future pass that starts generating control flow under a guard fails
loudly rather than being recorded as correct.

**A terminal had to be the last stage.** `expand |> chunkby |> map` would not
fuse, although `chunkby` hands back an array the rest of the chain can carry
on from. Relaxed -- and the warning that came with it was blaming `map`, which
is perfectly fusable, for a section a terminal had ended by design.

The pattern worth keeping from all six: every one lives where two features
meet, and each feature was correct alone. Fixtures written per feature cannot
find these, which is an argument for keeping a deliberately convoluted one
around and adding to it whenever something new lands.

### Where the passes meet

Each pass was right on its own. Probing pairs of them found three more, all
silent.

**`fallback` was not peeled first, despite saying so.** The hash pass runs
earlier and can turn one line into three; `split_prefix` has no `MULTILINE`,
so it then failed and handed back the whole block as the expression, with an
empty prefix. `nA := hCfg{"k"} fallback 0` put the assignment *inside* the
guard — on failure `nA` kept its old value and the fallback went nowhere. The
peel is genuinely first now, after only the comment peel, which has to precede
it or the comment lands inside the generated block.

**A postfix modifier after a bare chain stage disappeared.** `nB := aNums |>
asum if lFlag` left the last stage as `asum if lFlag`, and the bare-stage
branch takes the name and drops the rest without a word — the parenthesised
branch has a trailing-text check, the bare one never did. The modifier is read
off the source line now, before any pass sees it, which also fixes something
that was merely wrong rather than silent: every line the statement becomes
goes inside the generated `If`, not just the last one.

**A `defer` capturing a block local read a sibling block's value.** The body
runs at an exit from the function, so the variable has to outlive its block —
exactly the condition the escape analysis already tests for code block
captures, `@name` and `raw`. It was not in the list. The failure was as quiet
as this project gets: the origin comment on the generated line still named the
original variable while the slot held the sibling's string. `defer` pins now,
and `<contained>` in a defer is refused for the same reason, which is the
right reading — a defer *is* a way out of the block.

The lesson is the one the pass order already implied: each of these is a pass
that assumes it sees the line as written. Two of the three were fixed by
moving a peel earlier rather than by changing what any pass does.

### The trapdoor, and closing it

The main loop is a chain of branches, most of which `continue`. Everything
below the branch that fires is skipped, silently, and nothing said so. That is
one structural fault, and it produced the same bug in every construct that
takes an expression before the rewrites run.

`defer` was the first found. Probing the rest turned up seven more in
declaration initialisers alone — every construct xtpl has:

    local nA := hCfg{"id"}               emitted with its braces intact
    local cD := lookupName(1) ?: "anon"  emitted with '?:' intact
    local lE := nX %% 3                  emitted with '%%' intact
    local lF := cC in aC                 emitted with 'in' intact
    local nB := aNums |> asum            "'asum' is not declared"
    local cG := oUser?.oA?.cB            "'oA' is not declared"
    local nH := riskyCall(1) fallback 0  "'fallback' is not declared"

The first four are silent and reach the AdvPL compiler. The last three fail
here, but blame an undeclared name — the value had gone straight to the
undeclared-name check with nothing rewritten, so the verb of a chain looks
exactly like a variable nobody declared. The prologue is where initialisers
are written, so this is the worst-placed bug the project has had.

The same fault covered `for`'s source, `for <n> times`' count, `if local`
and `while local`'s binding and condition, `do case with`'s subject, and
`with object`'s subject.

Fixed once, with `rewrite_value(value, scope, idx, indent)`: it runs the
expression through `rewrite_statement` and hands back the statements the value
had to lift out of itself, plus the expression to put where the value went.
Every one of those sites calls it. `tests/test_initialisers` covers all of
them.

Found on the way: `local hM := {"a" => 1}  // note` did not build a
`THashMap`. `hash_literal_pairs` tested that the value ended in `}`, and a
trailing comment is a masked token sitting after it, so the literal was
emitted as an ordinary assignment. The comment is peeled first now.

**What has not been fixed is the shape.** `raw` still `continue`s, and so do
the branches that handle removed constructs and migration errors. `raw` is
meant to, and is documented as such. The rest are checks that emit nothing, so
they are safe today — but the loop offers no way to say which, and the next
construct added to it will face the same choice with no guardrail.

### Trailing comments, and the shape of the bug

A comment is masked into one token that travels with the tail of its line.
Every pass that wraps that tail in generated syntax therefore wraps the
comment too, and the comment eats the closing bracket:

    nSafe := riskyCall(1) fallback 0  // note
    -> nSafe := u_xtpl_safe_pipe({|| riskyCall(1)}, {|| 0  // note})

Same for `?:`. This is the third appearance of one bug — the loop headers had
it first, in the form of an end-of-line anchor that could not see past the
token. Fixed once now, centrally: the comment is peeled before the expression
rewrites and put back on the last physical line afterwards, so no pass has to
know comments exist. `tests/test_comments` covers all eight passes.

Two things learned re-recording the goldens for it. Sixteen fixtures broke
first time, because a comment-*only* line peeled to nothing and came back
indented; `peel_comment` now leaves a line alone when there is no code to
protect. And the comment's original column cannot be kept — the emitted line
is a different length from the source — so it is normalised to two spaces
everywhere rather than pretending.

### `defer` bodies were never translated, and why

A deferred body is spliced into the exit paths *after* every pass has run, so
an xtpl construct in one reached the output as written. `defer xconout(...)`
and `defer closeItem(hCfg{"id"})` emitted invalid AdvPL silently; `defer
aRows |> flush()` tripped the leftover `|>` check and blamed the return line
it had been spliced into, which is a confusing place to be sent.

**Fixed properly, by lifting the pipeline out of the loop.** The whole
expression-rewriting section is now `rewrite_statement(line, scope, idx)`, a
function rather than forty lines wedged into the middle of the main loop, and
`defer` calls it on its body like anything else. The interim rejection is
gone. `tests/test_defer` pins a body per construct.

The extraction itself was behaviour-neutral, verified against the fixtures
before `defer` was changed to use it. It needed one hidden coupling cut:
`transpile_feed_chains` was reading `fallback_val` straight out of the
enclosing loop, so it only worked when called from that one place. It takes
`guarded` as an argument now.

**Why this shape of bug existed.** A branch that `continue`s early in the main
loop skips every pass below it, silently, and nothing says so. `defer`, `raw`,
declarations and the loop headers all `continue`. That is the structural
reason a deferred body was never translated, and the same trapdoor is still
open for the other three.

**Two more found while fixing it.** A defer reaching a `return` was resolved
as part of that line, while one reaching the end of the body was not — so the
same text could be renamed in one exit path and left alone in the other, and a
variable read *only* by an end-of-function defer was reported as `assigned but
never read`, because the pass that counts reads never saw it. Both go away by
resolving the body once, where it is written.

### Operand spans: three bugs in one neighbourhood

Probing the passes still on the line scanner turned up three defects, all of
them an operator that did not know where its operand ended.

- **`f(cCod in aCodes, nX)` emitted `u_xtpl_in(cCod, aCodes, nX)`.** The
  membership regex looked ahead for `)`, `.and.`, `.or.` or end of line, by
  position and with no notion of depth, so a sibling argument was swallowed
  into the collection. This one compiled and was wrong, which makes it the
  worst of the three. Note that the obvious patch — adding `,` to that
  lookahead — would have broken `nValor in {1, 2, 3}` instead. Only the node
  list gets both right, because a comma inside braces is that group's, not
  this level's.
- **`oUser?.oA?.oB?.cCity` left a `?.` in the output.** The pattern handled at
  most two links. It now matches the whole chain and builds one guard per link
  but the last.
- **`(nValor + 1) %% 3` passed through untouched**, because the dividend
  pattern could only be a name or an indexed name. The node list supplies the
  parenthesised group as the left operand.

The last two fail loudly — invalid AdvPL — so they would have surfaced at the
first compile. The first would not have.

Worth recording: the fix for membership initially dropped the space in front
of `.and.`, emitting `u_xtpl_in(c, a).and. x`. `test_operators` caught it on
the next run. That is the second time this session a golden file has caught a
whitespace regression that no amount of reading the diff would have, and it is
the argument for having written them before starting the migration.

### Review of the grammars, and what it found

Eleven questions came back from a read of `xtpl_grammar.raku`. Each was tested
against the grammar rather than reasoned about; the verdicts split three ways.

**Real bugs, fixed.**

- **`return(x) if c` was not a return.** `<ret>` required whitespace after the
  keyword, so the parenthesised form fell through to `<plain>`. The transpiler
  then matched its own `return` prefix test first, emitted the pending defers,
  and passed the line through untouched — `return(x) if c` reached the `.tlpp`
  verbatim. The regex path had always accepted it, so the two paths disagreed,
  which is precisely what the golden tests exist to prevent and what no
  fixture happened to cover. `»` for a word boundary fixes it.
  `tests/test_postfix_return` pins all three return shapes.
- **`XtplPostfix::TOP` did not consume leading whitespace.** Not live, because
  the transpiler hands it a stripped line, but an indented `return x if c`
  parsed as `plain` and silently lost its defers — the same failure as above
  reached by a different route. A grammar that only works on pre-stripped
  input is a trap for its next caller.
- **`<contained >` was rejected while `< contained>` was accepted.** `:sigspace`
  inserts whitespace between atoms but not before the closer the goal operator
  supplies. Written out as a token, both sides now behave the same.
- **`%%` allowed a trailing separator**, so `local a := 1,` parsed as a list of
  one and the empty tail was dropped. `%` refuses it. The regex fallback was
  silently accepting it too and had to be brought into line, or the change
  would have created a fresh divergence. `errors/decl_trailing_comma` pins it.

**Correct as they stood, now with the reasoning written down.**

- **Quoted strings in `XtplDecl::value`, and the broad `<plain>` body.** Both
  are safe only because the transpiler masks every literal and comment before
  any pass sees a line. `local x := "a, b", y := "c"` reaches the grammar as
  `local x := <token>, y := <token>`. Parsed unmasked, both grammars get these
  wrong — worth knowing before reusing either one elsewhere, and now said so
  in the file.
- **Trailing garbage after a declarator** was already refused: `a := 1)` does
  not parse, because `)` is neither a value character nor the start of a
  group. The `$` was added anyway, so the property is stated rather than
  inferred from a character class.
- **`|` versus `||` in `XtplPostfix`.** Both give the same answer on every
  shape tested, because the three alternatives end at the same place and an
  LTM tie falls to the first. That is a coincidence of these patterns, not a
  property worth depending on, so it now reads `||` like the others.
- **`.Array` on the attribute list** is defensive, not required — rakulang
  reifies on the way to Python either way. Kept, because a `Seq` can only be
  consumed once and the value is read more than once downstream.

**Judged and partly declined.**

- **More keywords in `<control>`.** The right test is whether a word opens or
  closes a block, since the harm is a generated `If` wrapping something that
  belongs to a structure. By that test the structured-exception and
  declaration words were missing and have been added. `exit` and `loop` were
  deliberately left out: they are ordinary statements, and `exit if nX > 5` is
  a useful thing to write, which listing them would refuse. `return` stays out
  because `<ret>` handles it.

The pattern across all eleven is worth keeping: the two that mattered were
both cases where the grammar path and the regex path disagreed, and neither
was visible from reading the grammar alone.

The approach is one construct at a time, each verified byte-for-byte. Next
candidate: `apply_with_object`'s colon rewriting, which is a character scanner
rather than a depth counter and so is the one least likely to be served by the
node list. Probed this session against colons after `(`, `,`, inside `iif`,
and inside a string literal — it handled all of them, so there is no known bug
driving it, and it should probably wait for one.

Raku++ was checked before committing to this: grammars, actions classes,
`make`/`made`, `proto token` alternatives, longest-token matching and
lookaround all behave identically to Rakudo, and it starts in 3 ms against
Rakudo's 215. `probe.raku` and `probe2.raku` are those checks.

## Working style that produced good results

Build the thing, run it, read the output. Nearly every bug this project found
came from generating real output and looking at it, not from reasoning:

- `orwith` compiled to `ElseIf`, so the re-probe only ran when the first probe
  had already *succeeded*
- `?:` didn't chain, and didn't work inside expressions
- `fallback` over a fold left the chain's statements outside the guard
- end-of-function defers landed outside the function
- `defer` bodies were stored unmasked, so string contents were rescanned as code
- the transpiler's own reduce lambdas used bare names and tripped its own check
- `;` line continuation was unsupported — found by writing a real file in xtpl
  rather than a fixture
- a doc example had perfectly correlated features, so the model reported wrong
  coefficients while predicting correctly

Every trade is named rather than hidden: `distinct` gives up speed for order and
type freedom; `sort` copies to stay consistent with the rest of the runtime;
`fallback` folds a chain into one long line to keep every stage guarded; `raw`
gives up checking to accept code xtpl cannot parse; slot recycling gives up
debugger names and pays them back as comments.

Write the test, then read what it produced.
