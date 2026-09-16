# xtpl — language reference

*Versão em português: [language.md](language.md). Essa é a principal.*

Version 02, 2026-08-29.

A preprocessor that compiles `.xtpl` source to AdvPL `.tlpp`.

Part of this language is also available without the transpiler, as native
`#xtranslate` rules — see `xtpl_ch.md`. The syntax is identical; the header
covers the sugar, the transpiler adds variable lifetime, storage reuse and the
compile-time checks.

Everything below compiles against stock AdvPL except the functions in
[Arrays](#arrays) and `fallback`, which call `xtpl_runtime.tlpp`. Compile that
into a custom RPO once and generated files link against it.

---

## Variables

### Declarations belong in a prologue

A declaration is only legal in the run of declarations, comments and blank lines
that opens a function or a block. The first executable statement closes it.

```xtpl
user function calcTotal(nRate)
  local nBase := 100
  local aRows := {}

  nBase := nBase * nRate      // prologue closed here
  local nExtra := 5           // ERROR
```

> `Line 6: declaration of 'nExtra' must come before the first statement of its function or block.`

Block headers that declare are exempt, because they declare into the block they
are opening: `if local x := …`, `while local x := …`, `for local i := …`.

### Several declarators on a line

```xtpl
local a := 1, b, c := {10, 20}
```

Commas inside braces, brackets or parentheses are not separators, so an array
literal stays with its own declarator.

### Block locals have stack lifetime

A `local` inside a block behaves like a C++ automatic variable. It is fresh on
entry, gone on exit, and cannot be redeclared in the same block.

```xtpl
if nTotal > 50
  local nDiscount := 10
  nTotal := nTotal - nDiscount
endif

conout(nDiscount)             // ERROR
```

> `Line 6: 'nDiscount' is out of scope here (block local declared on line 2).`

The freshness matters because everything is hoisted to a function-level `Local`
in the generated code. Without an explicit reset, a `local` in a loop body would
quietly keep the previous iteration's value.

### Storage is shared where it is safe

Two sibling blocks at the same nesting depth get the same slot:

```xtpl
if nTotal > 0
  local nFirst := 1
endif

if nTotal > 0
  local cSecond := "different type, same storage"
endif
```

```advpl
Local __stk_1_0   // nFirst, cSecond

if nTotal > 0
  __stk_1_0 := 1                            // __stk_1_0 = nFirst
endif

if nTotal > 0
  __stk_1_0 := "different type, same storage"  // __stk_1_0 = cSecond
endif
```

A slot used by a single variable takes that variable's name --
`__stk_1_aTmp` -- and needs no origin comment. Only a slot shared by several
keeps a number, and there the comments say what it holds on each line.

Slots are named `__stk_<depth>_<slot>` and pooled per nesting depth, so nesting
never shares — an inner block is a level deeper and gets its own slot. The
declaration lists every variable that ever uses a slot, and each line names what
the slot currently holds, so a name in a debugger is always traceable back to
source.

A slot shared by several variables has no honest name, so it gets a
preprocessor rule and each line spells it with the name of whatever occupies
it there:

```advpl
#translate let <name1> as <name2> =>
#translate !<name>^<num1>^<num2>! => __stk_<num1>_<num2>
#translate !<name>^<num>! => __stk_<num>_<name>
#translate %<name>^<num>% => __blk_<num>_<name>

if nTotal > 0
  let aTmp as __stk_1_0
  !aTmp^1^0! := {}
endif

if nTotal > 0
  let cOther as __stk_1_0
  !cOther^1^0! := "different type, same storage"
endif
```

`#translate`, not `#xtranslate` -- the two do not behave the same here.

**Every block variable is written `!name^...!`.** Two numbers means the
storage is shared and has no honest name; one means the slot is named after
its only occupant. `%name^n%` is the one that got no slot: pinned by a capture, a `@`, a `raw`
line or a `defer`, or a lambda's parameter.

The markers substitute into the result's own name. The leading `!` stops it matching a genuine `a^2^3`; the trailing one
closes the pattern, without which the last marker swallows what follows --
which shows up as a mangled `For` header, that being the construct with text
to the right of the spelling. `let` marks the declaration while generating
nothing.

### What cannot be shared

Only one thing stops a variable sharing a slot: **being captured by a code
block.**

```xtpl
if nTotal > 0
  local nFator := 10
  aadd(aHandlers, {|| nFator * 2})
endif
```

A code block captures the *variable*, not its value — AdvPL detaches the local
and the block holds a live reference to that storage. Rebind the slot in a
later block and the block sees the new value. So `nFator` gets private
`__blk_<scope>_<name>` storage instead.

This has nothing to do with types. A captured number is exactly as unsafe as a
captured array.

**Passing a variable to a function is not a hazard**, whatever the function
does with it. AdvPL hands over the *object*; rebinding our name afterwards
cannot reach it. All of these are fine, and all of them still share a slot:

```xtpl
registerRows(aRows)      // callee keeps the array: still the same object
aadd(aOutras, aRows)     // stored elsewhere: still the same object
aOutras := aRows         // two names, one object
return aRows             // caller has the object
```

Three more routes to the same place as a code block, all pinned: `@nome` hands
over the variable itself; a `raw` line goes to a command the transpiler cannot
see into — `GET` in particular binds the variable to a dialog that outlives
the block; and a `defer` body runs at an exit from the *function*, long after
the block is gone, so recycling the slot in between would leave the defer
reading a sibling block's value.

The decision is made per declaration, not per name. Two blocks may each declare
an `aTmp`; they are different variables that never coexist, so one being
captured says nothing about the other.

### `let` -- where a block variable is declared

Every block-local declaration gets a marker in the generated code:

```advpl
let nFator as __blk_1_nFator
let aTmp as __stk_1_aTmp
let cOther as __stk_1_0
```

It says the name you wrote and the storage it got -- private because it was
captured, a slot of its own, or a shared one. It generates nothing.

The markers group at the top of the block they belong to, so the generated
code shows the shape xtpl requires of the source: declarations, then
statements. The exception is a variable declared **by** a header, as in
`for local nI := 1 to 3`, where the line that opens the block is the line that
uses it -- there the marker sits immediately above the header.

A lambda's parameter gets no marker: it is declared in the code block's own
parameter list, and the name is spelled out there already.

### Markers

Two annotations, for variables whose handling you want to state explicitly.

**`local x <contained>`** — a promise the compiler *enforces*. `x` may not be
captured by a code block, passed with `@`, or used on a `raw` line, anywhere in
the function. Worth reaching for in long functions: the declaration keeps
holding when someone adds a call 300 lines later.

```xtpl
local aWork <contained> := {}
aadd(aWork, "row")            // fine
processRows(aWork)            // fine -- passing hands over the object
aadd(aH, {|| aWork})          // ERROR
```

> `Line 4: 'aWork' is <contained> (declared on line 1) and cannot leave its block.`

Attributes go in angle brackets after the name, comma separated, and attach to
their own declarator:

```xtpl
local aWork <contained> := {}, nAux, aBuf <contained>
```

Between a name and `:=` no AdvPL expression can appear, so `<` and `>` are
unambiguous there — an ordinary comparison elsewhere in the line is untouched.

### TLPP types

TLPP's own type annotation is accepted and emitted back:

```xtpl
local oTool as object
local nTotal as numeric := 0
local nOutro := 1 as numeric        // the other order, equally accepted
```
```advpl
Local oTool as object
Local nTotal := 0 as numeric
Local nOutro := 1 as numeric
```

The type is emitted **after** the initialiser, which is how TLPP writes it,
whichever order the source used.

xtpl does nothing with it — no checking, no inference — but it does not make
anyone drop it either. A block local sharing a recycled slot loses the
annotation, since the slot is shared and a type from one declaration cannot be
claimed for it.

### Function headers

`function`, `user function`, `main function` and `static function`. All four
are just a function as far as xtpl is concerned.

If no header is recognised in a file, xtpl says so: nothing would be inside a
function, and the whole file would fall out copied unchanged.

A `function` with **no qualifier** is refused, because Protheus refuses it:

> `Line 10: a bare 'function' is not allowed by Protheus. Write 'user function', 'static function' or 'main function'.`

It passes under `--legacy`, where the point is to read the file as it is.

### Namespaces

A dotted path ending in a call is a TLPP namespace and passes through
untouched:

```xtpl
oTool := totvs.tools.ListCustomerCreditData.ListCustomerCreditData():New()
```

Ending in a call is what tells it from `nA.And.nB`, which is lexically
identical.

### `private` — dynamic scope

A `PRIVATE` is visible to everything the function calls. That is how a
Protheus dialog lets a button's code block reach a control built by whoever
created it:

```xtpl
function abreTela()
  private oMGet

  oMGet := TMultiget():New(...)
  oBtn := TButton():New(..., {|| leCodigo()})
  ...

static function leCodigo()
  oMGet:setFocus()          // comes from the caller
```

Declared in one place, **the name is known for the whole file** — that is what
dynamic scope means to xtpl. Unlike `external`, which only promises the name
exists, a `private` can be assigned anywhere too.

**But the variable only exists while the function that declared it is on the
stack.** Declaring one in a helper that returns immediately achieves nothing:
it is gone before anything can read it, and the error is
`variable does not exist` at run time. Declare it in the function that stays
up for as long as it is needed.

Emitted **after** every `Local`, not before: `Private x := v` is an
executable statement, and a `Local` following one is rejected by the
preprocessor.

No slot recycling, no block scope, no attributes: nothing here can promise
what happens to a name visible to the whole call stack. A `private` the
declaring function never reads is not reported — existing for what it calls is
the normal case.

Writing to an **undeclared** name also creates a `PRIVATE`, and that is the
anti-pattern xtpl refuses. `private` is how to say the same thing on purpose.

### Parameters

Parameters are registered from the signature, so they can be assigned and
defaulted like any other variable, and shadowing one is an error.

---

## Operators

### `?=` — defined-or

Assigns only when the target is still Nil.

```xtpl
cCache ?= "empty"
```

```advpl
If cCache == Nil
  cCache := "empty"
EndIf
```

It is an operator on an existing variable, never a declaration form — a fresh
local is always Nil, so the test could not fail there. `local x ?= v` is
rejected; write `local x := v`.

The three `?` operators are distinct, and easy to conflate:

| | what it does | where |
|---|---|---|
| `?.` | safe member access | between object and member |
| `?:` | the value, or a fallback if Nil | any expression |
| `?=` | **assigns** if the variable is Nil | statement of its own |

And `?:` is not `fallback`: `?:` catches **Nil**, `fallback` catches a
**runtime error**.

`?=` is a statement of its own, never part of an expression. For a value that
falls back when Nil, inside an expression, use `?:`:

```xtpl
(myCall() ?= {}) |> tap(...)     // ERROR
(myCall() ?: {}) |> tap(...)     // right
```

### `?:` — elvis

The nickname comes from Groovy and Kotlin: turned sideways, `?:` looks like a
quiff over two eyes. Also called the *null-coalescing operator*.

Nothing to do with member access — that operator is `?.`, just above. `?:`
works on any expression.

Yields the left side unless it is Nil. The left side is bound to a temp first, so
it is evaluated exactly once.

```xtpl
cName := lookupName(1) ?: "anonymous"
```

```advpl
__elvis_tmp_0_0 := lookupName(1)
cName := If(__elvis_tmp_0_0 != Nil, __elvis_tmp_0_0, "anonymous")
```

Chains nest, so each fallback runs only if the previous returned Nil, and works
inside expressions — a nested chain is lifted into statements ahead of the line,
whole, which is what preserves the short-circuit.

```xtpl
cPick := first() ?: second() ?: "last resort"
aadd(aItems, loadItem(1) ?: "placeholder")
```

### `?.` — safe navigation

Also called *safe call* (Kotlin), *optional chaining* (TypeScript) and
*null-conditional* (C#). All the same operator.

A missing link yields Nil instead of crashing.

```xtpl
cCity := oUser?.oAddress?.cCity
```

```advpl
cCity := If(oUser != Nil .And. oUser:oAddress != Nil, oUser:oAddress:cCity, Nil)
```

Any number of links. Every one but the last is tested; the last is only read.

---

## Control flow

### Conditional binding

Bind a value and test it in one line. The variable is scoped to the block.

```xtpl
if local lReady := checkReady(), lReady
  conout("ready")
endif

while local cNode := nextNode(), cNode != Nil
  conout("node: " + cNode)
enddo
```

### `for`

Binds the element directly. The index is optional and only generated when you
name it.

```xtpl
for oItem in aItens
  nTotal := nTotal + oItem:nValor
next

for oItem, nIndice in aItens
  conout(cValToChar(nIndice) + ": " + oItem:cCodigo)
next
```

```advpl
__stk_1_0 := aItens
For __stk_1_2 := 1 To Len(__stk_1_0)
  __stk_1_1 := __stk_1_0[__stk_1_2]
  ...
Next
```

The source is bound once, since it may be a call and it is indexed on every
pass. Element, index and the two hidden variables are all ordinary block locals
of the loop's own scope, so they are slot-recycled like anything else and
sibling loops share their storage.

**Arrays only.** Harbour's `FOR` also walks hashes, strings and objects,
deciding at runtime; a transpiler has to choose one lowering at compile time
and has no type to go on. Handing it something else raises a normal AdvPL error
at `Len()`, which `try` / `catch` can take.

### `for <n> times`

Repeats without inventing a counter you never read.

```xtpl
for 3 times
  conout("linha")
next

for contaLinhas(oDoc) times
  nTotal := nTotal + 1
next
```

```advpl
For __stk_1_0 := 1 To 3
  conout("linha")
Next

__stk_1_1 := contaLinhas(oDoc)
For __stk_1_0 := 1 To __stk_1_1
  nTotal := nTotal + 1
Next
```

A literal count goes straight into the header. Anything else is bound first, so
a call sits above the loop rather than inside it. The counter is a hidden block
local, slot-recycled like any other.

### `do case with`

AdvPL's `Do Case` is untouched. The optional `with` clause evaluates the
subject once and gives it a name — the one thing plain `Do Case` cannot do,
since every `Case` repeats the expression.

```xtpl
do case with local nSub := calcTotal(n)
  case nSub == 6
    c := "seis"
  case nSub > 3
    c := "maior"
  case isReady(nSub)
    c := "pronto"
  otherwise
    c := "pequeno"
endcase
```

```advpl
__stk_1_0 := calcTotal(n)
Do Case
  case __stk_1_0 == 6
  ...
endcase
```

The conditions are ordinary AdvPL, so there is nothing new to read. With
`local` the subject is a fresh block local — scoped, slot-recycled, and it may
carry `<const>`. Without it, the subject assigns to a variable declared
earlier:

```xtpl
do case with nOutro := calcOutro(n)
```

### `with object`

For code that repeats the same subject on every line — FWModel work, mostly.
The subject is evaluated once and bound; inside the block a leading `:` means
"the subject".

```xtpl
with object oModel:GetModel("SA1DETAIL")
  :SetValue("A1_COD", cCod)
  :SetValue("A1_NOME", cNome)
  cNome := :GetValue("A1_NOME")
end with
```

```advpl
__stk_1_0 := oModel:GetModel("SA1DETAIL")
__stk_1_0:SetValue("A1_COD", cCod)
__stk_1_0:SetValue("A1_NOME", cNome)
cNome := __stk_1_0:GetValue("A1_NOME")
```

`oModel:GetModel(...)` runs once rather than once per line, which is the point
as much as the brevity.

A `:` that follows a name, `)` or `]` is ordinary member access and is left
alone, as are `::` for self and `:=` for assignment. What gets replaced is a
colon in a position where AdvPL could not have put one. Blocks nest — the
innermost subject wins, and the outer resumes at its `end with`.

The holder is an ordinary block local, so it is slot-recycled like anything
else.

### `using alias` — a scoped work area

Selects an alias, optionally sets an index order, and puts back what it found
at **every** way out of the block — including an early `return`.

```xtpl
using alias SA1 order 1 do
  nTotal := SA1->A1_SALDO
  return nTotal if nTotal > 100
end using
```

```advpl
__stk_1_0 := Alias()
DbSelectArea("SA1")
__stk_1_1 := SA1->(RecNo())
__stk_1_2 := SA1->(IndexOrd())
SA1->(DbSetOrder(1))
  nTotal := SA1->A1_SALDO
  If nTotal > 100
    SA1->(DbSetOrder(__stk_1_2))
    SA1->(DbGoto(__stk_1_1))
    If !Empty(__stk_1_0)
      DbSelectArea(__stk_1_0)
    EndIf
    Return nTotal
  EndIf
SA1->(DbSetOrder(__stk_1_2))
SA1->(DbGoto(__stk_1_1))
If !Empty(__stk_1_0)
  DbSelectArea(__stk_1_0)
EndIf
```

Forgetting to restore an alias is a classic Protheus bug, and its damage shows
up somewhere else entirely — which is what makes the early `return` the case
worth having. The record pointer goes back too: a walk inside the block leaves
the area at `Eof`, and the caller did not ask for that.

`order` is optional, and the index order is only saved and restored when one
is given.

A bare word is the alias itself, since `using alias SA1` is how it reads.
A variable in scope holds one instead:

```xtpl
using alias SA1 do          // the alias
using alias cAlias do       // a variable holding one
```

Blocks nest, and each keeps its own saved state. This shares the `defer`
machinery, so the two agree on order at a `return`: **deferred statements
first**, since they may still want the area, then the work areas, innermost
block first.

The holders are ordinary block locals, so they are slot-recycled like anything
else.

### `defer`

Registers a statement to run before every exit from the function, in reverse
order of registration.

```xtpl
defer closeCursor()
defer logExit("finished")
```

Emitted before each explicit `return` and at the natural end of the body.

The body is an ordinary statement and goes through the same passes as any
other line, so a chain, a hash read or an `xconout` in one is translated. A
body that becomes several statements stays together wherever it is spliced:

```xtpl
defer aRows |> validate() |> flush()
```
```advpl
__pipe_tmp_0_0 := validate(aRows)
flush(__pipe_tmp_0_0)
```

Names are resolved where the `defer` is written, not where it runs, so both
exit paths emit the same thing — and a variable read only by a defer counts
as read.

### Postfix modifiers

```xtpl
lDone := .T. if nTotal > 5
exec resetAll() if nTotal == 0
conout("counting") while nTotal < 0
return nTotal if nTotal > 100
```

A postfix `return` runs the pending defers first.

---

## Hashes

Dictionaries over `THashMap`, without the `Set`/`Get` ceremony.

```xtpl
local hCfg := {"taxa" => 0.05, "limite" => 1000}
local hVazio := {=>}

nTotal := nBase * hCfg{"taxa"}
hCfg{"limite"} := 2000

if hCfg has "taxa"
  conout("tem taxa")
endif
```

```advpl
hCfg := THashMap():New()
hCfg:Set("taxa", 0.05)
hCfg:Set("limite", 1000)

__hash_tmp_0_0 := Nil
hCfg:Get("taxa", @__hash_tmp_0_0)
nTotal := nBase * __hash_tmp_0_0

hCfg:Set("limite", 2000)

__hash_tmp_1_0 := Nil
If hCfg:Get("taxa", @__hash_tmp_1_0)
```

**Braces subscript a hash, brackets subscript an array** — the Perl split. A
`{` directly after a name is a hash access, which AdvPL never has, so the two
are told apart by syntax and no type tracking is needed. A brace group whose
top-level parts are all `k => v` is a hash literal; anything else is an array.
`{=>}` is the empty hash.

Reading lifts into a statement, since `Get` is not an expression. The temp is
cleared first because `Get` leaves the variable untouched when the key is
absent, so a miss reads back as `Nil`. `has` rides on `Get`'s logical return,
so the existence test costs nothing extra.

`Clean()` is not generated — it is a convenience, not a requirement.

### Walking a hash

`for` walks arrays, so a hash could not be iterated at all. `keys`, `values`
and `pairs` return arrays, so everything else composes with them unchanged:

```xtpl
for cChave in keys(hCfg)
  conout("${cChave} = ${hCfg{cChave}}")
next

nTotal := values(hSaldos) |> asum
aMv    := keys(hCfg) |> filter([k] starts(k, "MV_"))
cLista := keys(hCfg) |> sort |> join(", ")
```

`pairs` keeps them together, one `{chave, valor}` row per entry.

They go through `THashMap:List(@aOut)`, which fills `{{key, value}, ...}`
and builds the whole array — a hash is in
memory and finite, so there is nothing to stream and no reason for these to be
sources like `rows` and `lines`.

**The order is whatever the hash gives back.** Nothing here sorts, because
most uses do not need it and `|> sort` is there when they do.

## Arrays

### Array functions

Ordinary calls, collection first, matching `aEval` and `aScan`. A lambda is
`[alias] body`, with up to six names — `[acc, x] body` for `reduce`, `[a, b, c]`
for a three-way `zip`.

```xtpl
aVals  := map(aOrders, [o] o:nValue)
aBig   := filter(aOrders, [o] o:nValue > 1000)
aLive  := reject(aOrders, [o] o:lCancelled)
nTotal := reduce(aNums, [acc, x] acc + x, 0)
aTop   := sortBy(aOrders, [o] o:nValue, .T.)
```

The full set, all from `xtpl_runtime.tlpp`:

| | |
|---|---|
| `map`, `filter`, `reject` | transform, keep, discard |
| `reduce(a, block, seed)` | fold with an explicit seed |
| `fold(a, block)` | fold from the first element; `Nil` if empty |
| `take`, `drop` | first or all-but-first *n* |
| `asum`, `aprod`, `amax`, `amin` | fold with a fixed operator |
| `in(x, a)` | membership, behind the `in` operator |
| `sort(a [, cmp])` | natural order, or a two-element comparator |
| `sortBy(a, key [, lDesc])` | by an extracted key, ascending unless told otherwise |
| `distinct`, `reverse`, `flatten` | `flatten` is recursive |
| `enumerate` | `{index, value}` pairs |
| `chunks` | fixed-size blocks |
| `zip(a, b, ... [, block])` | two to six arrays, up to the shortest length |

`zip` takes any number of arrays from two to six, and treats a code block in any
argument position as the combiner. Mismatched lengths are clipped silently, as
in Raku.

`sort` and `sortBy` copy before sorting. `aSort` works in place, so without the
copy they would reorder the caller's array — and inside a `|>` chain, the array
feeding the stage. Every function here returns a new array and leaves its input
alone.

Each compiles to a `u_xtpl_`-prefixed name, which keeps them clear of a function
of the same name already in the codebase — but it also means a call to *your*
`take()` will be redirected to the runtime's. Rename yours, or drop the name
from `runtime_verbs`.

### Folds

`asum`, `aprod`, `amax` and `amin` collapse an array into one value. `fold`
covers anything else.

```xtpl
nTotal := asum(aNums)
nMax   := amax(aNums)
nMaior := fold(aNums, [acc, x] Iif(len(x) > len(acc), x, acc))
```

The `a` prefix follows `aScan` and `aSort`, and keeps `amax`/`amin` clear of
AdvPL's own two-argument `Max` and `Min`, which a plain `max` would have
captured on every existing call.

`asum` and `aprod` start from 0 and 1, so they are safe on an empty array.
`amax`, `amin` and `fold` start from the first element and return `Nil` when
there is nothing to fold.

Being ordinary calls, they chain:

```xtpl
nTotal := aOrders |> filter([o] o:lPago) |> map([o] o:nValor) |> asum
```

### `in` — membership

```xtpl
if cCodigo in aCodigos
if nValor in 1..100
```
```advpl
If u_xtpl_in(cCodigo, aCodigos)
If (nValor >= 1 .And. nValor <= 100)
```

AdvPL's `$` searches a string only, so an array needs `aScan`. A range is two
comparisons and needs no runtime at all.

The collection ends at the first comma, bracket or `.and.` / `.or.` **at the
same level**, so `f(cCod in aCodigos, nValor)` reads as one membership test
and one further argument, while `nValor in {1, 2, 3}` keeps its literal
whole.

### `%%` — divisible by

```xtpl
if nValor %% 3
if (nValor + 1) %% 3
```
```advpl
If (nValor % 3) == 0
If ((nValor + 1) % 3) == 0
```

`%` itself is AdvPL's own modulo and passes through untouched.

### A chain does not nest, but the verbs are ordinary functions

A `|>` chain cannot sit inside a lambda -- lifting its stages out of the block
would run them before the block does, and there is no correct place to put
them. But every chain verb is also a plain function, and calling one directly
inside the lambda works:

```xtpl
|> filter([a] len(a) == 3 .and. allof(a, ehNumero))
|> map([a] asum(map(a, val)) / 3)
```

In practice that removes almost every helper function the restriction appears
to demand.

### `|>` — feed

Sugar for chaining: the value on the left becomes the **first argument** of the
stage on the right. That is the only rule — it knows nothing about the four
functions above, so it composes them and your own helpers identically.

```xtpl
aCodes := aOrders |> filter([o] o:nValue > 1000) |> map([o] o:cCode)
aCodes := aOrders |> myOwnHelper(3) |> sortRows
```

```advpl
__pipe_tmp_0_1 := u_xtpl_filter(aOrders, {|__blk_0_o| __blk_0_o:nValue > 1000})
__pipe_tmp_0_2 := u_xtpl_map(__pipe_tmp_0_1, {|__blk_0_o| __blk_0_o:cCode})
aCodes := __pipe_tmp_0_2

__pipe_tmp_0_3 := myOwnHelper(aOrders, 3)
__pipe_tmp_0_4 := sortRows(__pipe_tmp_0_3)
aCodes := __pipe_tmp_0_4
```

Each stage lands in its own temp, so nothing is evaluated twice. Those temps
are pooled per statement — they live for exactly one line, so the names are
reused down the function.

A chain run for its effects needs no result. With no assignment or `return` in
front, the last stage is a statement in its own right:

```xtpl
aPedidos |> valida() |> grava()
```
```advpl
__pipe_tmp_0_0 := valida(aPedidos)
grava(__pipe_tmp_0_0)
```

A chain with no assignment has no result to build, and so **fuses with no
accumulator** — it becomes exactly the loop somebody would have written:

```xtpl
aCobertura |> filter([r] upper(r[1]) == cAlvo) |> tap([r] VarInfo("COBERTURA", r))
```
```advpl
__fuse_src_0_0 := aCobertura
For __fuse_i_0_0 := 1 To Len(__fuse_src_0_0)
  __fuse_v_0_0 := __fuse_src_0_0[__fuse_i_0_0]
  __blk_0_r := __fuse_v_0_0
  If upper(__blk_0_r[1]) == cAlvo
    __blk_0_r := __fuse_v_0_0
    VarInfo("COBERTURA", __blk_0_r)
  EndIf
Next
```

The same over a source: `rows("SA1") |> tap([r] conout(r:A1_COD))` walks the
table building nothing.

A chain inside an expression is lifted into its own statement first, so it
composes anywhere. A single stage needs no temp of its own — the call it
becomes is already an expression, and it is left where it stood:

```xtpl
nTotal := len(aNums |> distinct)
nTotal := aNums |> filter([x] x > 100) |> asum
```
```advpl
nTotal := len(u_xtpl_distinct(aNums))

__pipe_tmp_0_0 := u_xtpl_filter(aNums, {|__blk_0_x| __blk_0_x > 100})
nTotal := u_xtpl_asum(__pipe_tmp_0_0)
```

The lift is bounded by the brackets and commas around the chain, so a chain in
one argument leaves the others alone.

**Not inside a code block.** A block body runs later; lifting a stage out of
one would run it now, and there is no correct place to put it instead.

```xtpl
aOut := map(aNums, [x] x |> triple)     // ERROR
```

> `Line 3: '|>' cannot chain inside a code block -- lifting its stages out would run them before the block does.`

Write the stage as an ordinary nested call — `[x] triple(x)` — or chain over
the whole array rather than inside the lambda.

### Fusion

A chain is one call per stage, and each call walks its input and builds a new
array. Three stages over a large array is three loops and two arrays thrown
away. Where the stages look at one element at a time, they are emitted as the
body of a **single loop** instead.

```xtpl
aTop := aRows |> filter([r] r:nSaldo > 0) |> map([r] r:cCod) |> take(10)
```

```advpl
__fuse_src_0_0 := aRows
__fuse_out_0_0 := {}
__fuse_n_0_0 := 0
For __fuse_i_0_0 := 1 To Len(__fuse_src_0_0)
  __fuse_v_0_0 := __fuse_src_0_0[__fuse_i_0_0]
  __blk_0_r := __fuse_v_0_0
  If __blk_0_r:nSaldo > 0
    __blk_0_r := __fuse_v_0_0
    __fuse_v_0_0 := __blk_0_r:cCod
    If __fuse_n_0_0 >= 10
      Exit
    EndIf
    __fuse_n_0_0 := __fuse_n_0_0 + 1
    AAdd(__fuse_out_0_0, __fuse_v_0_0)
  EndIf
Next
aTop := __fuse_out_0_0
```

No array between the stages, and `take` is an `Exit` rather than a function
that runs after everything has already been computed — so the loop stops at
ten rather than walking the rest.

### `takewhile` and `dropwhile`

`filter` keeps every match, anywhere. `takewhile` keeps the matching run at
the front and **stops at the first failure** — it does not look at the rest.

```xtpl
aFrente := aRows |> takewhile([r] r:nSaldo > 0)
```

Over an ordered source that is the whole point: once the key changes, the rest
is known not to match, so reading it would learn nothing.

`dropwhile` is the mirror — skip the leading run, then pass everything,
including elements that would have matched. That is why it needs a flag rather
than a test.

**Give `rows` a key and it seeks instead of starting at the top**, which is
what makes `takewhile` worth having on a large table — reach the group in one
jump, then stop at its end:

```xtpl
using alias SC6 order 1 do
  aItens := rows("SC6", xFilial("SC6") + cNum) ;
            |> takewhile([r] r:C6_NUM == cNum) ;
            |> map([r] r:C6_PRODUTO)
end using
```

The seek uses whatever index order is set, so `using alias ... order N` around
the chain is how to be sure which. A seek that finds nothing lands on `Eof`,
so the walk produces nothing — no test of its own is needed.

Without a key it still starts at the top, and the two stages compose to reach
a group by reading rather than seeking:

```xtpl
aGrupo := rows("SC6") |> dropwhile([r] r:C6_NUM != cNum) |> takewhile([r] r:C6_NUM == cNum)
```

Correct, and it never reads past the group — but it reaches it by scanning.

`map`, `filter`, `reject`, `take`, `drop`, `takewhile` and `dropwhile` fuse. `asum`, `aprod`, `amax`,
`amin` and `join` fuse as the last stage, and then no array is built at all —
`join` writes the string directly:

```xtpl
cLista := aRows |> map([r] r:cCod) |> join("; ")
```

`join` is the only *named* terminal that takes an argument. A flag marks the
first element rather than testing the accumulator for emptiness, which would
lose the separator after a legitimately empty first element.

**`reduce` and `fold` fuse too**, and they are the reason the fusable
terminals are not a closed list of names. They carry their own combining step,
so the transpiler needs to know nothing in advance — an aggregation of your
own fuses exactly like a built-in one:

```xtpl
cLista := aRows |> map([r] r:cCod) |> reduce([acc, x] acc + "; " + x, "")
cLongo := aRows |> map([r] r:cNome) |> fold([acc, x] Iif(len(x) > len(acc), x, acc))
```

The seed is evaluated once, before the loop. `fold` is the seedless form: the
first element is the starting value, so it stays `Nil` until one arrives.

A block held in a variable — `reduce(bBlock, 0)` — cannot be inlined, so the
chain falls back to the runtime call and says so.

### `scan`, `expand`, `tap` and `pairwise`

**`scan`** is `reduce` that keeps its working — the accumulator after every
element rather than only the last. A running balance is why it exists:

```xtpl
aSaldos := aMovs |> map([m] m:nValor) |> scan([acc, x] acc + x, 0)
```

Movements `{100, -30, 50}` give `{100, 70, 120}`, where `reduce` would give
`120`. The running value carries on down the chain, so
`|> scan(...) |> filter([s] s < 0)` finds every point the balance went
negative.

**`expand`** turns one element into however many the block returns — the
inverse of `filter`, which turns one into zero or one:

```xtpl
aProdutos := rows("SC5") |> expand([r] itensDoPedido(r:C5_NUM)) |> map([i] i:cProduto)
```

For each order, its items, and the chain carries on with the **items**. It
becomes a loop inside the loop, so nothing is materialised — `map` then
`flatten` would build every item list before flattening any of them.

**`tap`** runs a block for its effect and hands the element back untouched, so
a chain can be looked into without being taken apart:

```xtpl
aCodigos := aRows |> filter([r] r:nSaldo > 0) |> tap([r] conout(r:cCod)) |> map([r] r:cCod)
```

**`pairwise`** gives each element with the one before it. The first has no
predecessor, so *n* elements give *n-1* pairs:

```xtpl
aDeltas := aLeituras |> map([l] l:nMedidor) |> pairwise |> map([p] p[2] - p[1])
```

`scan` and `pairwise` need a value to carry, so over `rows` they want a `map`
first. `tap` and `expand` read the record and do not.

### `distinctAdjacent` — and how it differs from `distinct`

Two names, two algorithms, and they are the names those algorithms have
elsewhere.

| | compares against | passes | fuses |
|---|---|---|---|
| `distinct` | everything kept so far | O(n²) | no |
| `distinctAdjacent` | the previous element only | O(n) | yes |

`distinctAdjacent` compares each element against the one before it, so it
drops runs. `distinct` compares against everything kept so far, so it drops
duplicates anywhere. **Over unsorted input they give different answers**, so
the choice is not a matter of taste.

It does not require sorted input, and does not check for it — sorted input is
the common case, not a precondition. Collapsing runs in a chronological
sequence, to find where a value changed, is an equally good use.

```xtpl
aPedidos := aRows |> map([r] r:cPedido) |> distinctAdjacent
```

With a key it compares that instead of the element — which over an ordered
table gives the distinct values of a field in one pass:

```xtpl
using alias SC6 order 1 do
  aNumeros := rows("SC6") |> distinctAdjacent([r] r:C6_NUM) |> map([r] r:C6_NUM)
end using
```

Without a key over `rows` there is nothing to compare, since a record is not a
value, and it is refused.

### `maxby` and `minby`

The largest **element** by an extracted key, where `amax` gives the largest
key and loses the row it came from:

```xtpl
nMaior := aRows |> map([r] r:nValor) |> amax      // 15000
oMaior := aRows |> maxby([r] r:nValor)            // the row worth 15000
```

Otherwise you sort everything to look at one of them — and `sort` blocks
fusion, so that builds an intermediate array too.

### `first` and `count`

`first` gives the first match and stops there. `count` says how many match
without building the array of them.

```xtpl
oAtrasado := aRows |> map([r] r:oPed) |> first([p] p:lAtraso)
nGrandes  := aRows |> map([r] r:nValor) |> count([v] v > 100)
```

Both replace `filter(...)` followed by a look at the result — which builds an
array to answer a question that needs none, and in `first`'s case keeps
searching after the answer is known. `first` yields `Nil` when nothing
matches.

`count` with no condition counts what reaches it, which is how to size a walk
over something that has no length until it has been read:

```xtpl
using alias SC6 order 1 do
  nItens := rows("SC6", xFilial("SC6") + cNum) |> takewhile([r] r:C6_NUM == cNum) |> count
end using
```

`count` reads the element, so over `rows` it needs no `map` first. `first`
does need one: it hands the element back, and a work-area record is not a
value.

### `chunkby`

Groups **consecutive** elements sharing a key — one array per group, in one
pass, holding only one group at a time.

```xtpl
using alias SC6 order 1 do
  aGrupos := rows("SC6", xFilial("SC6") + cNum) ;
             |> map([r] {r:C6_NUM, r:C6_PRODUTO}) ;
             |> chunkby([x] x[1])
end using
```

That is the header/detail walk, which is otherwise a nested loop with an inner
`Eof()` test that is easy to get wrong.

**Consecutive is the word that matters.** It cuts the sequence where the key
changes; it does not gather scattered matches. Over unsorted input the same
key comes back more than once. This is not `GROUP BY` — and it is precisely
what lets it stream.

Over a work area the key block reads the value a `map` produced, not the
record, since after a map the element is whatever the map made of it.

### Predicates

`anyof`, `allof` and `noneof` ask whether elements match, and **stop as soon
as they know**:

```xtpl
lAtraso := aRows |> anyof([r] !r:lPago)
lTodosOk := aRows |> map([r] r:nValor) |> allof([v] v > 0)
```

Without them the question needs a filtered array and a `len()`, which reads
the whole collection to answer something usually settled by the first element.

They read the element rather than a value made from it, so over a work area no
`map` is needed first — and the walk itself stops:

```xtpl
lNegativo := rows("SA1") |> anyof([r] r:A1_SALDO < 0)
```

leaves the table at the first negative balance instead of reading to `Eof`. A lambda has
to be written at the stage — a code block held in a variable cannot be
inlined.

**Only the leading run.** `sort` cannot produce anything until it has seen the
last element; `distinct` has to remember what it has seen. Those and the rest
carry on as ordinary stages, from the array the loop built, and xtpl says so:

```
warning: line 31: 'sort' cannot be fused -- it needs the whole collection, so it and every stage after it builds an array
```

The warning fires only when the chain was using the element-wise verbs in the
first place; a chain of ordinary functions was never a candidate and is left
alone.

**A single stage is left as a call.** One stage is one loop either way, so
fusing it would only make the output longer.

### Sources

`rows` and `lines` are **sources**, not functions. A source is something to
walk, and it appears in exactly two places:

```xtpl
aCodigos := rows("SA1") |> map([r] r:A1_COD)     // at the head of a chain
for cLinha in lines(cPath)                       // as a 'for' source
```

**A source is not a value.** It cannot be assigned to something and used
later, passed to a function, or held — there is nothing to hold, because a
source is walked rather than produced. Anywhere else it is refused:

```xtpl
nQuantas := len(lines(cPath))     // ERROR
```

> `Line 11: 'lines()' is a source, and only reads at the head of a chain. Assign it, or feed it into stages with '|>'.`

That is the whole rule, and the restrictions on each source below follow from
it rather than being separate rules to learn.

**Running the walk to completion is the exception.** A chain with no stages
has nowhere to stream to, so it builds the array:

```xtpl
aTodas := lines(cPath)            // every line
```

`rows` cannot do this, for a reason particular to it: a work-area record is
not a value, so there is nothing to collect without a `map` first.

Sources are named as plural nouns for what they yield. `items` is reserved for
a third, over any object that can be walked; it does not exist yet.

**Why the restriction exists.** Laziness here is a compile-time property, not
a runtime one. There is no object carrying an iterator — the transpiler writes
one loop with the stages inside it, which it can only do when it can see the
whole pipeline in one statement. Raku's `lines` can be held in a variable
because its runtime has an iterator protocol; AdvPL has none, and building one
would mean an `Eval` per element per stage and output that no longer resembles
what was written.

### `rows` — a work area as a source

A work area is already a lazy sequence with an awkward calling convention:
`DbGoTop()` starts it, `Eof()` tests it, `DbSkip()` advances it. `rows` gives
it the same shape as an array, and the chain fuses into the walk — so the
table is read a record at a time and never loaded.

```xtpl
nTotal := rows("SA1") |> filter([r] r:A1_SALDO > 0) |> map([r] r:A1_VALOR) |> asum
```

```advpl
__fuse_area_0_0 := Alias()
DbSelectArea("SA1")
__fuse_rec_0_0 := SA1->(RecNo())
SA1->(DbGoTop())
__fuse_out_0_0 := 0
While !SA1->(Eof())
  If SA1->A1_SALDO > 0
    __fuse_v_0_0 := SA1->A1_VALOR
    __fuse_out_0_0 := __fuse_out_0_0 + __fuse_v_0_0
  EndIf
  SA1->(DbSkip())
EndDo
SA1->(DbGoto(__fuse_rec_0_0))
If !Empty(__fuse_area_0_0)
  DbSelectArea(__fuse_area_0_0)
EndIf
nTotal := __fuse_out_0_0
```

The selected area and the record pointer are put back afterwards. Leaving an
alias somewhere else is a classic Protheus bug whose damage appears in code
that had nothing to do with the line.

`rows(alias, key)` seeks instead of going to the top; see
[takewhile](#takewhile-and-dropwhile).

A literal alias is written out, since `SA1->A1_COD` is what a Protheus
developer reads. Anything else is bound once and reached through AdvPL's
parenthesised form, `(cAlias)->A1_COD`.

**The element is the record, not a value.** `r:A1_COD` compiles to a field
reference; the name cannot be used for anything else, because there is no
object to pass:

```xtpl
rows("SA1") |> filter([r] isOk(r))     // ERROR
```

> `Line 4: over rows() the element is the current record, not a value, so it can only be used to name a field.`

And a chain has to `map` the record to a value before anything can be
collected from it — there is nothing else to collect.

Its stages must be ones that can be fused into the walk. `sort` and `distinct`
cannot, and a `take` after them would no longer stop the scan.

### `lines` — a file as a source

The same protocol as `rows`, over text. `FT_FUse` opens the file,
`FT_FReadLn` reads one line, `FT_FSkip` advances, `FT_FUse()` closes — the
idiom Protheus already uses, so the file is never held in memory and a `take`
really does stop the read.

```xtpl
aTop := lines("dados.txt") |> filter([l] !empty(l)) |> map([l] alltrim(l)) |> take(10)
```

```advpl
__fuse_src_0_0 := "dados.txt"
FT_FUse(__fuse_src_0_0)
FT_FGoTop()
__fuse_n_0_0 := 0
__fuse_out_0_0 := {}
While !FT_FEof()
  __fuse_v_0_0 := FT_FReadLn()
  __blk_0_l := __fuse_v_0_0
  If !empty(__blk_0_l)
    __blk_0_l := __fuse_v_0_0
    __fuse_v_0_0 := alltrim(__blk_0_l)
    If __fuse_n_0_0 >= 10
      Exit
    EndIf
    __fuse_n_0_0 := __fuse_n_0_0 + 1
    AAdd(__fuse_out_0_0, __fuse_v_0_0)
  EndIf
  FT_FSkip()
EndDo
FT_FUse()
aTop := __fuse_out_0_0
```

Unlike `rows`, the element **is** a value — the line — so a lambda parameter
binds to it in the ordinary way.

**As a `for` source**, when the body is statements rather than a chain:

```xtpl
for cLinha, nNumero in lines(cPath)
  if empty(cLinha)
    loop
  endif
  return nNumero if cLinha == cProcurado
next
```

This works where `for` over `rows` would not: the element here **is** a
value, so it binds to a name in the ordinary way. A work-area record is not a
value, which is why the same shape is refused there.

The file advances straight after the line is read, not at the foot of the
loop, so a `loop` in the body is safe. An early `return` closes the file on
its way out, the same as a work area is restored.

**No stages is still a chain**, and reads every line:

```xtpl
aTodas := lines(cPath)
```

A stage that cannot be fused ends the walk rather than preventing it:
`lines(cPath) |> sort` collects the lines and sorts them, because sorting
cannot begin before the last line is known.

If the file will not open, the walk produces nothing and the result is empty.

**Text only.** `FT_FReadLn` splits on line endings and AdvPL strings are bytes,
so a binary file does not fail — it is silently cut at every 0x0A byte, and
whatever the FT_ family's maximum line length is will truncate a file that has
no line endings at all, which is what a binary file looks like. There is no
`bytes(file)` counterpart; use `FOpen` and `FRead` directly for that.

`lines` and `rows` are source names, so those two words are taken.

### `fallback`

Guards an expression: if it raises, yield the fallback instead. Works on a bare
call, a `return`, or a whole `|>` chain.

```xtpl
e := riskyCall(1) fallback "default"
n := aNums |> filter([x] x > 1000) |> asum fallback 0
```

```advpl
e := u_xtpl_safe_pipe({|| riskyCall(1)}, {|| "default"})
```

Both sides are code blocks, so the fallback runs only when the protected side
actually fails. `u_xtpl_safe_pipe` swaps the error block for one that breaks on
a runtime error and restores it afterwards, because a bare `BEGIN SEQUENCE`
catches only `Break()`.

`fallback` is peeled from the line before anything else rewrites it, so
everything the line goes on to generate ends up inside the guard. They become
comma-separated expressions in the block, which keeps each stage evaluated once
while leaving nothing outside the protection.

**Under a guard a chain does not fuse, and xtpl says so.** A code block body is comma-separated
expressions, and a fused loop is `While`/`EndDo`, which is not one. An array
chain falls back to the runtime calls, which are expressions. A source has no
unfused form, so it cannot be guarded at all:

```xtpl
nTotal := rows("SA1") |> map([r] r:A1_SALDO) |> asum fallback 0     // ERROR
```

> `Line 10: 'fallback' cannot guard a walk over rows(). The guard needs an expression and a walk is a loop. Assign the chain first, then guard what uses it.`

Losing a pass is invisible in the source, so it is reported:

```
warning: line 22: 'fallback' turns off fusion for this chain -- a guard needs an expression and a fused loop is not one, so each stage builds an array again. Guard the part that can fail instead, and leave the chain outside it.
```

Guarding only the part that can fail is nearly always better, leaving the
chain outside. A guard in brackets is lifted into a statement of its own and
the chain fuses as usual:

```xtpl
aList := (riskyCall(2) fallback {}) |> filter([x] x > 1) |> map([x] x * 2)
```
```advpl
__guard_tmp_0_0 := u_xtpl_safe_pipe({|| riskyCall(2)}, {|| {}})
__fuse_src_0_0 := __guard_tmp_0_0
For ...
```

### Strings

The runtime carries only what AdvPL lacks. `Upper`, `Lower`, `AllTrim`,
`PadL`, `PadR`, `StrTran` and the rest already take their subject first, so
they chain as they stand — and wrapping them would shadow the originals on
every existing call in the codebase.

```xtpl
cOut := cNome |> alltrim |> upper          // AdvPL's own, nothing added
```

| | |
|---|---|
| `split(text, sep)` | to an array, on a separator of any length |
| `join(parts, sep)` | back to a string |
| `starts(text, what)`, `ends(text, what)` | prefix and suffix |
| `contains(text, what)` | `$` reads needle-first, which is the usual way to get it wrong; this takes the text first, like everything else |

### Interpolation

```xtpl
cMsg := "total = ${nTotal} itens"
```
```advpl
cMsg := ("total = " + cValToChar(nTotal) + " itens")
```

The literal becomes a concatenation before any other pass sees it, so an
expression inside one is ordinary code — a hash read included:

```xtpl
cMsg := "taxa ${hCfg{'t'}} fim"
```

**An interpolated expression cannot use the same quote as the string around
it.** Literals are masked before anything runs, so the inner quote ends the
outer string:

```xtpl
cMsg := "taxa ${hCfg{"t"}} fim"      // ERROR
```

> `Line 9: '${' in a string is never closed. An interpolated expression cannot use the same quote as the string around it -- write '...' inside "...".`

### `xconout`

```xtpl
xconout("total=", nBig, " items")
```

```advpl
conout("total=" + cValToChar(nBig) + " items")
```

String literals are passed through; everything else is wrapped in
`cValToChar`.

## `queue`

A first-in, first-out queue. The one data structure worth adding: AdvPL arrays
are already dynamic, so a stack is `AAdd` plus `ATail` plus `aSize`, but
taking from the **front** means `ADel` then `aSize`, which moves every
remaining element once per pop. This is a ring buffer, so a pop moves nothing.

```xtpl
local oFila := queue()          // or queue(256) for an initial size

for oPedido in aPedidos
  oFila:Push(oPedido)
next

while !oFila:IsEmpty()
  oProximo := oFila:Pop()
next
```

| | |
|---|---|
| `Push(x)` | add at the back |
| `Pop()` | take from the front, `Nil` when empty |
| `Peek()` | the front without taking it |
| `Count()`, `IsEmpty()` | how many, and whether any |

It grows by doubling when it fills, so the initial size is a hint, not a
limit. `Pop()` gives `Nil` on an empty queue — ask `IsEmpty()` first if `Nil`
is a value you might legitimately have queued.

The class is `XtplQueue`, and that name is taken, like the runtime verbs.

## Removed

| Was | Why | Now |
|---|---|---|
| `let` | Duplicated `local` once `local` gained stack semantics | `local` |
| `gather` / `take` | Eager and lexical, so no better than `aadd`; the useful version needs dynamic scope | build the array |
| `given` / `when` | An `if`/`elseif` chain with new vocabulary. `Do Case` says the same thing in AdvPL a Protheus developer already reads; the only gap was naming the subject, which `do case with` fills | `do case with` |
| `?=>` | Chained like the feed operator but without the verbs, and broken without `fallback` | `|>` plus `fallback` |
| `local x ?= v` | A fresh local is always Nil, so the test never fails | `local x := v` |
| `==>`, then `=>` | Renamed; `=>` collides with the preprocessor's own separator and with hash literals | `|>` |
| `Z` | Renamed | `zip` |
| `with` / `orwith` / `without` | The probe result was never bound, so a branch could not use it; `without x do` is just `If x == Nil` | `?:` for first-non-Nil, `if` for the rest |

Each raises a migration error naming the replacement rather than emitting
invalid AdvPL.

---

## Line continuation

A trailing `;` joins a line with the next, as in AdvPL. The statement is
processed as one logical line, so an operator may sit on either side of the
break.

```xtpl
cReply := HttpPost(cUrl, "", cBody, nTimeout, ;
                   {"Content-Type: application/json"}) fallback ""
```

Errors report the first line of the group.

A line whose brackets do not close is refused at once, since it could never be
a statement:

> `Line 3: this line's brackets do not close. If it carries on to the next one, end it with ';'.`

Forgetting the `;` is the commonest slip in a language that needs an explicit
continuation marker, and without this check the preprocessor only complains
much later.

The `;` is found past a trailing comment, so a comment may sit on a continued
line. It moves to the end of the joined statement, since once the lines are
one there is nowhere else for it to go.

## `raw` — hand a line to the preprocessor

A `#command` or `#xtranslate` rewrites *syntax*, not identifiers. So a line
like this is not AdvPL yet — it becomes AdvPL only after the preprocessor runs,
which is after xtpl:

```xtpl
raw @ 10, 5 SAY "Total" GET nTotal PICTURE "@E 999,999.99"
```

`raw` says: do not try to understand this line. There is a block form for
screens and dialogs:

```xtpl
raw
  @ 12, 5 SAY "Nome" GET cNome PICTURE "@!"
  @ 14, 5 SAY "Obs"  GET cNome SIZE 60, 10
end raw
```

**Declared variables are still renamed inside `raw`**, so block locals work
there like anywhere else. Only the undeclared-name check is relaxed, because
`SAY`, `GET` and `PICTURE` are commands, not variables.

A variable mentioned on a `raw` line is pinned, the same as one captured by a
code block. The transpiler cannot see what the command does with it, and `GET`
in particular passes by reference to a dialog that outlives the block.

## Includes

Every generated file gets these at the top:

```advpl
#include "totvs.ch"
#include "tlpp-core.th"
```

Only the ones the source has not already asked for -- a file that includes
`totvs.ch` itself does not end up with it twice.

## Encoding and line endings

The file is read as it was written. UTF-8, cp1252 and ISO-8859-1 are detected,
and the output goes back out in the same encoding with the same line ending --
writing UTF-8 from a latin-1 source would corrupt every accented string on the
way to a compiler that is not expecting it.

## Comments

Both AdvPL forms work. `/* ... */` is folded into `//` before anything else
reads the file, so a block comment may hold whatever it likes — a declaration,
a chain, an unbalanced brace — without any of it being read as code.

A block that ends part-way through a line has its text moved to the end of
that line, since `//` runs to the end and there is nowhere else for it to go:

```xtpl
nA := /* inline */ nX + 1
```
```advpl
nA :=  nX + 1  // inline
```

Line numbers are unaffected: no line is added or removed by the fold.

## Field checking

Off unless a dictionary is given. `SA1->A1_NMOE` when the field is `A1_NOME`
is a runtime error today, invisible to AdvPL and to the preprocessor.

```
python3 xtpl_transpiler.py --dict sx3.csv pedido.xtpl pedido.tlpp
```

```
warning: Line 22: 'SA1->A1_NMOE' is not a field of SA1. Did you mean A1_NOME?
warning: Line 23: alias 'SAX' is not in the dictionary. A table that is missing usually means the export is out of date.
```

The two are reported differently on purpose: **a missing field is usually a
typo, a missing table usually a stale export.** A close field name is
suggested where there is one.

Warnings by default, since a field being added may not be in an export yet and
a stale dictionary should not stop a build. `--dict-strict` turns them into
errors, for CI.

### Types and sizes

Where the export carries `X3_TIPO` and `X3_TAMANHO`, a field used with a
**literal** of the wrong type is reported, and so is a string too long to fit:

```
warning: Line 12: SA1->A1_NOME is character, assigned a numeric value.
warning: Line 17: SA1->A1_SALDO is numeric, compared with a character value.
warning: Line 31: SA1->A1_COD holds 6 characters, but is assigned 7.
```

That last one is silent truncation — AdvPL writes what fits and drops the
rest.

**Only literals are typed.** A field used with a variable is left alone:

```xtpl
SA1->A1_COD := cQualquer          // nothing is claimed
```

Inferring types across an untyped language is how a checker becomes a
false-positive machine. `Nil` is left alone too, since assigning it is
ordinary. An export without the type column still gives name checking.

The dictionary is a CSV export of SX3. Column names vary between exports, so
the table and field columns are found by what their headers contain — ARQUIVO,
ALIAS, TABELA or TABLE for one, CAMPO or FIELD for the other — and a file with
no recognisable header falls back to the first two columns.

**Chains are checked too.** A field named through `rows` has become an
ordinary field reference by the time it is emitted:

```xtpl
aC := rows("SA1") |> map([r] r:A1_NMOE)     // caught
```

What cannot be checked is an alias held in a variable — `rows(cAlias)` or
`(cAlias)->A1_COD` — since what it holds is not known here. Those are skipped
rather than guessed at.

## `--map`

Every emitted line carries the source line it came from.

```
python3 xtpl_transpiler.py --map pedido.xtpl pedido.tlpp
```

```advpl
__fuse_src_0_0 := aNums  // xtpl:11
For __fuse_i_0_0 := 1 To Len(__fuse_src_0_0)  // xtpl:11
  __fuse_v_0_0 := __fuse_src_0_0[__fuse_i_0_0]  // xtpl:11
```

One source line often becomes a dozen, so the marker goes on all of them
rather than the first — scanning upwards for the nearest one is exactly the
work this exists to remove. A runtime error in the `.tlpp` then reads back to
what was written.

## `--check`

Parse and report, write nothing. The output path becomes optional.

```
python3 xtpl_transpiler.py --check --dict sx3.csv pedido.xtpl
```

Warnings go to stderr as usual and the exit status is 0; an error exits 1.
With `--dict-strict` beside it, a dictionary warning becomes an error and
fails the run, which is the shape CI wants.

## Warnings

A declaration the function never reads is reported, distinguishing the two
mistakes:

```
warning: line 3: 'nEscrito' is assigned but never read
warning: line 4: 'nNuncaUsado' is declared but never used
```

The first usually means a leftover from an edit or a result nobody wanted; the
second, a typo that created a second variable or a declaration that outlived
its use. Warnings go to stderr and do not stop the build.

Parameters are not reported — an unused one is often part of an interface that
has to keep its shape.

## `--legacy`

One thing stops xtpl accepting an existing `.prw`: **a write to an undeclared
name.** AdvPL allows it and creates a `PRIVATE` — an anti-pattern, but legal —
while xtpl refuses it. `--legacy` makes it a warning.

Everything else xtpl checks here, AdvPL checks too. **Reading** an undeclared
name is an error in AdvPL as well, so that is not an xtpl restriction. Nor is
the prologue: AdvPL rejects a `Local` after the first statement, and a `Local`
inside a block, so no file that compiles today has either. The prologue is
relaxed anyway, as a convenience, and reported.

```
python3 xtpl_transpiler.py --legacy legado.prw legado.tlpp
```

```
warning: line 18: declaration of 'cNome' is not in a prologue
warning: line 26: 'cNaoDeclarado' is not declared, so this creates a PRIVATE
warning: line 28: 'SAY' is not declared
legacy: 1 declaration outside a prologue, 3 uses of 3 undeclared names
legacy: 1 implicit PRIVATE -- cNaoDeclarado
legacy: most used undeclared -- SAY (1), GET (1), PICTURE (1)
```

**Scoping is untouched.** Block-scoped `local` is something xtpl adds where
AdvPL has nothing, so there is no existing meaning to preserve and no reason
to turn it off. A declaration outside a prologue keeps its initialiser where
it was written, since folding it into the hoisted `Local` would run it at
function entry — a different program.

An undeclared name is left exactly as written and is **not** declared for you.
Declaring it would add a `Local` the source never had — and where the write
creates a `PRIVATE`, a `Local` would not even be the same thing.

**A name a write brought into being is reported once, where it happens.** The
reads after it are of a variable that by then exists, so they are not
reported; a read with no write before it still is, since AdvPL would reject
that too.

The counts at the end are as much the point as the warnings. `SAY`, `GET` and
`PICTURE` near the top say the file is command-shaped and wants `raw`, not
declarations — which is how to tell, before converting anything, whether a
file is worth converting at all.

Everything else still applies: removed constructs are still errors, `<const>`
and `<contained>` still hold, and field checking still runs.

## Returning a value on some paths only

```
warning: line 14: this returns nothing, but the function returns a value on line 11
warning: line 24: the function can reach its end without a return, but returns a value on line 20
```

The caller gets `Nil` and finds out somewhere else and later. AdvPL says
nothing about it.

## Call form

The compiler puts the `U_` on a `User Function`'s declaration, so it is
reached as `u_name`. A `Static Function` is called by its plain name. Getting
the two backwards compiles, links, and fails only when the line runs -- xtpl
checks the call against the declaration, both ways:

> `Line 3: 'u_ajuda' -- ajuda is a static function in this file, so it is called by its plain name, without the 'u_'.`

Only for functions declared in the same file; from another there is no way to
know.

## Argument counts

A call to a function declared in the same file is checked against its
signature. AdvPL checks none of this.

> `Line 10: calcTotal() takes 2 parameters (line 4), but is given 3.`

**Only too many is reported.** A missing parameter arrives as `Nil` and plenty
of code relies on that, so fewer is ordinary. An extra one cannot be reached
at all, so it is always a mistake. Under `--legacy` it is a warning.

## Everything must be declared

Reading an undeclared name is an error, not just assigning to one.

> `Line 3: 'nUndeclared' is not declared. Everything used in xtpl must be declared.`

These are not variable references and are left alone: a call (`name(`), a member
access (`oUser:cNome`), a database field (`SA1->A1_COD`), a logical literal
(`.T.`, `.And.`), a `#define` in the same file, and any name the transpiler
generated.

### `external alias`

For a work area the caller opens. The same promise `external` makes about a
name: it exists, this file just cannot see where it came from.

```xtpl
external alias SA1, SB1
```

Without it, a field reference against an alias nothing in the function opened
is reported:

> `line 30: nothing in this function opened SD1. Wrap the use in 'using alias SD1 do', or declare 'external alias SD1' if the caller opens it.`

`using alias`, `rows`, `DbSelectArea` and `ChkFile` all count as opening one.
Reported once per alias rather than once per use, and off under `--legacy`,
where an alias opened by the caller is the norm rather than the exception.

### `external`

For names that exist but that the transpiler cannot see — a constant from an
`#include` it does not read, or a `PUBLIC` set by a caller:

```xtpl
#include "totvs.ch"

external STR0042, STR0043        // constants from the message header
external cEmpAnt, cFilAnt        // PUBLIC, set before this runs
```

File level, beside the includes, because that is what these names are: a header
constant is visible throughout the file and a `PUBLIC` is visible everywhere.
It emits nothing — the generated code is unchanged.

**Readable, never assignable.** `external` says the name exists, not that it is
yours to write:

> `Line 5: 'cEmpAnt' is external (line 1) and cannot be assigned.`

It is a promise rather than a check, so a typo *inside* the declaration passes
silently. A `#define` in the same file needs no `external` — those are found
automatically.

A `#define` arriving through `#include` is not visible, nor is a `PUBLIC` set by
a caller. Both are what `external` is for. A bare field name used without its
alias still has no answer.

## Not checked

Both attributes are on the declaration, so there is nothing to write at a call
site. Passing a variable to a function needs no marker.
