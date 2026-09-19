# xtpl — referência da linguagem

*English version: [language.en.md](language.en.md).*

Um transpilador que compila fontes `.xtpl` para `.tlpp` AdvPL.

Tudo abaixo compila contra AdvPL padrão, exceto as funções em
[Arrays](#arrays), `fallback` e a classe `queue`, que chamam
`xtpl_runtime.tlpp`. Compile esse arquivo em um RPO customizado uma vez, e os
arquivos gerados linkam contra ele.

As mensagens de erro citadas aqui aparecem em inglês porque é assim que o
transpilador as emite.

---

## Variáveis

### Declarações pertencem ao prólogo

Uma declaração só é válida na sequência de declarações, comentários e linhas em
branco que abre uma função ou um bloco. O primeiro comando executável fecha
essa sequência.

```xtpl
user function calcTotal(nTaxa)
  local nBase := 100
  local aLinhas := {}

  nBase := nBase * nTaxa      // prólogo fechado aqui
  local nExtra := 5           // ERRO
```

> `Line 6: declaration of 'nExtra' must come before the first statement of its function or block.`

Cabeçalhos de bloco que declaram são exceção, porque declaram dentro do bloco
que estão abrindo: `if local x := …`, `while local x := …`, `for local i := …`.

### Vários declaradores em uma linha

```xtpl
local a := 1, b, c := {10, 20}
```

Vírgulas dentro de chaves, colchetes ou parênteses não são separadores, então
um literal de array permanece com seu próprio declarador.

### Locais de bloco têm tempo de vida de pilha

Um `local` dentro de um bloco se comporta como uma variável automática de C++.
É nova na entrada, some na saída, e não pode ser redeclarada no mesmo bloco.

```xtpl
if nTotal > 50
  local nDesconto := 10
  nTotal := nTotal - nDesconto
endif

conout(nDesconto)             // ERRO
```

> `Line 6: 'nDesconto' is out of scope here (block local declared on line 2).`

Essa "novidade" a cada entrada importa porque tudo é içado para um `Local` de
nível de função no código gerado. Sem uma limpeza explícita, um `local` no
corpo de um laço guardaria silenciosamente o valor da iteração anterior.

### O armazenamento é compartilhado onde é seguro

Dois blocos irmãos na mesma profundidade recebem o mesmo slot:

```xtpl
if nTotal > 0
  local nPrimeiro := 1
endif

if nTotal > 0
  local cSegundo := "outro tipo, mesmo armazenamento"
endif
```

```advpl
Local s_1_0   // nPrimeiro, cSegundo

if nTotal > 0
  s_1_0 := 1                            // s_1_0 = nPrimeiro
endif

if nTotal > 0
  s_1_0 := "outro tipo, mesmo armazenamento"  // s_1_0 = cSegundo
endif
```

Um slot usado por uma só variável leva o nome dela —
`s_1_aTmp` — e não precisa de comentário de origem. Só um slot
compartilhado por várias fica numerado, e aí os comentários dizem o que ele
contém em cada linha.

Os slots se chamam `s_<profundidade>_<slot>` e são agrupados por
profundidade de aninhamento, então aninhar nunca compartilha — um bloco interno
está um nível abaixo e recebe seu próprio slot. A declaração lista todas as
variáveis que já usaram um slot, e cada linha diz o que o slot contém naquele
momento, de modo que um nome no depurador sempre pode ser rastreado até o
fonte.

Um slot dividido por várias variáveis não tem nome honesto, então recebe uma
regra do pré-processador e cada linha o escreve com o nome de quem o ocupa:

```advpl
#translate let <name1> as <name2> =>
#translate !<name>^<num1>^<num2>! => s_<num1>_<num2>

if nTotal > 0
  let aTmp as s_1_0
  !aTmp^1^0! := {}
endif

if nTotal > 0
  let cOutro as s_1_0
  !cOutro^1^0! := "outro tipo, mesmo armazenamento"
endif
```

`#translate`, não `#xtranslate` — os dois não se comportam igual aqui.

**Só um slot dividido leva grafia.** Os outros nomes já dizem de quem são —
`s_1_aTmp`, `b_0_nFator` —, e a grafia seria pontuação em volta de algo
legível. Com dois números o
armazenamento é dividido e não tem nome honesto; com um só, o slot leva o nome
de quem o ocupa, que é o único. `%nome^n%` é a que não ganhou slot: fixada por uma captura, um `@`, uma linha
`raw` ou um `defer`, ou o parâmetro de um lambda.

Os marcadores entram no próprio nome do resultado. O `!` na frente impede que a regra case com uma potenciação de
verdade, `a^2^3`; o `!` no fim fecha o padrão, sem o qual o último marcador
engole o que vem depois — o estrago aparece num cabeçalho `For`, que é onde há
texto à direita da grafia. `let` marca a declaração sem gerar nada.

### O que não pode ser compartilhado

Só uma coisa impede uma variável de compartilhar um slot: **ser capturada por
um code block.**

```xtpl
if nTotal > 0
  local nFator := 10
  aadd(aHandlers, {|| nFator * 2})
endif
```

Um code block captura a *variável*, não seu valor — o AdvPL destaca o local e o
bloco guarda uma referência viva àquele armazenamento. Reatribua o slot em um
bloco posterior e o code block enxerga o novo valor. Por isso `nFator` recebe
armazenamento privado `b_<escopo>_<nome>`.

Isso não tem nada a ver com tipos. Um número capturado é exatamente tão inseguro
quanto um array capturado.

**Passar uma variável para uma função não é um risco**, faça a função o que
fizer com ela. O AdvPL entrega o *objeto*; reatribuir nosso nome depois não
alcança aquilo. Todos estes casos são seguros, e todos continuam compartilhando
slot:

```xtpl
registraLinhas(aLinhas)  // a função guarda o array: continua o mesmo objeto
aadd(aOutras, aLinhas)   // guardado em outro lugar: continua o mesmo objeto
aOutras := aLinhas       // dois nomes, um objeto
return aLinhas           // quem chamou tem o objeto
```

Mais três caminhos para o mesmo lugar de um code block, todos fixados: `@nome`
entrega a própria variável; uma linha `raw` vai para um comando que o
transpilador não consegue enxergar — `GET` em particular liga a variável a uma
janela que sobrevive ao bloco; e um corpo de `defer` roda numa saída da
*função*, muito depois do bloco ter acabado, então reciclar o slot no meio-tempo
deixaria o defer lendo o valor de um bloco irmão.

A decisão é por declaração, não por nome. Dois blocos podem cada um declarar um
`aTmp`; são variáveis diferentes que nunca coexistem, então uma ser capturada
não diz nada sobre a outra.

### `let` — onde uma variável de bloco é declarada

Toda declaração de variável de bloco recebe um marcador no código gerado:

```advpl
let nFator as b_1_nFator
let aTmp as s_1_aTmp
let cOutro as s_1_0
```

Diz o nome que você escreveu e o armazenamento que ele recebeu — privado
porque foi capturado, um slot só seu, ou um slot dividido. Não gera nada.

Os marcadores ficam agrupados no topo do bloco a que pertencem, então o código
gerado mostra a mesma forma que o xtpl exige do fonte: declarações, depois
comandos. A exceção é uma variável declarada **pelo** cabeçalho, como em
`for local nI := 1 to 3`, onde a linha que abre o bloco é a mesma que a usa —
aí o marcador fica logo acima do cabeçalho.

O parâmetro de um lambda não leva marcador: ele é declarado na própria lista
de parâmetros do code block, e o nome já aparece por extenso.

### Marcadores

Duas anotações, para variáveis cujo tratamento você quer declarar
explicitamente.

**`local x <contained>`** — uma promessa que o compilador *faz cumprir*. `x` não
pode ser capturada por um code block, passada com `@`, nem usada em uma linha
`raw`, em nenhum lugar da função. Vale a pena em funções longas: a declaração
continua valendo quando alguém acrescentar uma chamada 300 linhas depois.

```xtpl
local aTrabalho <contained> := {}
aadd(aTrabalho, "linha")      // ok
processaLinhas(aTrabalho)     // ok -- passar entrega o objeto
aadd(aH, {|| aTrabalho})      // ERRO
```

> `Line 4: 'aTrabalho' is <contained> (declared on line 1) and cannot leave its block.`

**`local x <const>`** — não pode ser reatribuída, passada com `@`, nem alterada
de nenhum modo que o transpilador consiga ver. Precisa de um valor na
declaração, já que nunca poderá receber outro.

Atributos vão entre sinais de menor e maior depois do nome, separados por
vírgula, e se aplicam ao seu próprio declarador:

```xtpl
local aTrabalho <contained> := {}, nAux, aBuf <contained, const> := {}
```

Entre um nome e `:=` nenhuma expressão AdvPL pode aparecer, então `<` e `>` não
são ambíguos ali — uma comparação comum em outro ponto da linha fica intocada.

### Tipos do TLPP

A anotação de tipo do próprio TLPP é aceita e reemitida:

```xtpl
local oTool as object
local nTotal as numeric := 0
local nOutro := 1 as numeric        // a outra ordem, igualmente aceita
```
```advpl
Local oTool as object
Local nTotal := 0 as numeric
Local nOutro := 1 as numeric
```

O tipo é emitido **depois** do inicializador, que é como o TLPP o escreve,
seja qual for a ordem no fonte.

O xtpl não faz nada com ela — não verifica nem infere — mas também não obriga
ninguém a abandoná-la. Um local de bloco que divide um slot reciclado perde a
anotação, já que o slot é compartilhado e um tipo de uma declaração não pode
ser reivindicado para ele.

### Cabeçalhos de função

`function`, `user function`, `main function` e `static function`. Para o xtpl
são todos apenas uma função.

Se nenhum cabeçalho for reconhecido em um arquivo, o xtpl avisa: nada estaria
dentro de uma função, e todo o arquivo sairia copiado sem alteração.

Um `function` **sem qualificador** é recusado, porque o Protheus o recusa:

> `Line 10: a bare 'function' is not allowed by Protheus. Write 'user function', 'static function' or 'main function'.`

Sob `--legacy` passa, já que ali o objetivo é ler o arquivo como ele é.

### Namespaces

Um caminho pontuado que termina em chamada é um namespace do TLPP e passa
intocado:

```xtpl
oTool := totvs.tools.ListCustomerCreditData.ListCustomerCreditData():New()
```

Terminar em chamada é o que o distingue de `nA.And.nB`, que é lexicamente
idêntico.

### `private` — escopo dinâmico

`PRIVATE` é visível para tudo que a função chama. É assim que um diálogo
Protheus deixa o code block de um botão alcançar um controle construído por
quem o criou:

```xtpl
function abreTela()
  private oMGet

  oMGet := TMultiget():New(...)
  oBtn := TButton():New(..., {|| leCodigo()})
  ...

static function leCodigo()
  oMGet:setFocus()          // vem de quem chamou
```

Declarado em um lugar, **o nome é conhecido no arquivo inteiro** — é o que
escopo dinâmico significa para o xtpl. Diferente de `external`, que só promete
que o nome existe, um `private` também pode ser atribuído em qualquer lugar.

**Mas a variável só existe enquanto a função que a declarou estiver na
pilha.** Declará-la num auxiliar que retorna na hora não serve para nada: ela
some antes de alguém ler, e o erro é `variable does not exist` em tempo de
execução. Declare-a na função que fica de pé enquanto ela for necessária.

Emitida **depois** de todos os `Local`, e não antes: `Private x := v` é um
comando executável, e um `Local` depois de um comando é recusado pelo
pré-processador.

Não recicla slot, não tem escopo de bloco e não aceita atributos: nada aqui
pode prometer o que acontece com um nome visível para toda a pilha de chamadas.
Uma `private` que a própria função nunca lê não é relatada — existir para quem
ela chama é o caso normal.

Escrever em um nome **não declarado** também cria uma `PRIVATE`, e é o
anti-padrão que o xtpl recusa. `private` é como dizer a mesma coisa de
propósito.

### Parâmetros

Parâmetros são registrados a partir da assinatura, então podem ser atribuídos e
receber valor padrão como qualquer outra variável, e sombrear um deles é erro.

---

## Operadores

### `?=` — atribui se indefinido

Atribui apenas quando o alvo ainda é Nil.

```xtpl
cCache ?= "vazio"
```

```advpl
If cCache == Nil
  cCache := "vazio"
EndIf
```

É um operador sobre uma variável existente, nunca uma forma de declaração — um
local recém-criado é sempre Nil, então o teste nunca falharia ali.
`local x ?= v` é recusado; escreva `local x := v`.

Os três operadores com `?` são distintos e é fácil confundi-los:

| | o que faz | onde |
|---|---|---|
| `?.` | acesso seguro a membro | entre o objeto e o membro |
| `?:` | o valor, ou uma alternativa se for Nil | qualquer expressão |
| `?=` | **atribui** se a variável for Nil | comando isolado |

E `?:` não é `fallback`: `?:` trata **Nil**, `fallback` trata um **erro de
execução**.

`?=` é um comando isolado, nunca parte de uma expressão. Para um valor que
recorre a outro quando é Nil, dentro de uma expressão, use `?:`:

```xtpl
(minhaFunc() ?= {}) |> tap(...)     // ERRO
(minhaFunc() ?: {}) |> tap(...)     // certo
```

### `?:` — elvis

O apelido vem de Groovy e Kotlin: virado de lado, `?:` lembra um topete sobre
dois olhos. Também chamado de *operador de coalescência nula*.

Não tem relação com acesso a membros — o operador para isso é `?.`, logo
acima. `?:` funciona sobre qualquer expressão.

Devolve o lado esquerdo, a menos que ele seja Nil. O lado esquerdo é ligado a um
temporário primeiro, então é avaliado exatamente uma vez.

```xtpl
cNome := buscaNome(1) ?: "anônimo"
```

```advpl
__elvis_tmp_0_0 := buscaNome(1)
cNome := If(__elvis_tmp_0_0 != Nil, __elvis_tmp_0_0, "anônimo")
```

As cadeias aninham, então cada alternativa só roda se a anterior devolveu Nil, e
funciona dentro de expressões — uma cadeia aninhada é içada inteira para
comandos acima da linha, e é isso que preserva o curto-circuito.

```xtpl
cEscolha := primeiro() ?: segundo() ?: "último recurso"
aadd(aItens, carregaItem(1) ?: "reserva")
```

### `?.` — acesso seguro

Também chamado de *safe navigation* (Groovy), *safe call* (Kotlin),
*encadeamento opcional* (TypeScript) e *null-conditional* (C#). São todos o
mesmo operador.

Um elo ausente devolve Nil em vez de derrubar.

```xtpl
cCidade := oUsuario?.oEndereco?.cCidade
```

```advpl
cCidade := If(oUsuario != Nil .And. oUsuario:oEndereco != Nil, oUsuario:oEndereco:cCidade, Nil)
```

Qualquer quantidade de elos. Todos, menos o último, são testados; o último é
apenas lido.

---

## Controle de fluxo

### Ligação condicional

Liga um valor e o testa em uma linha só. A variável tem escopo do bloco.

```xtpl
if local lPronto := verificaPronto(), lPronto
  conout("pronto")
endif

while local cNo := proximoNo(), cNo != Nil
  conout("nó: " + cNo)
enddo
```

### `for`

Liga o elemento diretamente. O índice é opcional e só é gerado quando você o
nomeia.

```xtpl
for oItem in aItens
  nTotal := nTotal + oItem:nValor
next

for oItem, nIndice in aItens
  conout(cValToChar(nIndice) + ": " + oItem:cCodigo)
next
```

```advpl
s_1_0 := aItens
For s_1_2 := 1 To Len(s_1_0)
  s_1_1 := s_1_0[s_1_2]
  ...
Next
```

A origem é ligada uma vez, já que pode ser uma chamada e é indexada a cada
passagem. Elemento, índice e as duas variáveis ocultas são todos locais de bloco
comuns, do escopo do próprio laço, então reciclam slots como qualquer outra
coisa e laços irmãos dividem o mesmo armazenamento.

**Sem `each`.** As três formas de `for` se distinguem pelo formato — `:=` na
forma contada, `times` no fim, um `in` isolado — então a palavra não dizia nada.
Ela também tomava emprestada a grafia do Harbour para algo mais restrito: o
`FOR EACH` do Harbour percorre hashes, strings e objetos, decidindo em tempo de
execução.

**Somente arrays.** Um transpilador precisa escolher uma tradução em tempo de
compilação e não tem tipo em que se apoiar. Passar outra coisa levanta um erro
AdvPL normal no `Len()`, que `try` / `catch` pega.

### `for <n> times`

Repete sem inventar um contador que você nunca lê.

```xtpl
for 3 times
  conout("linha")
next

for contaLinhas(oDoc) times
  nTotal := nTotal + 1
next
```

```advpl
For s_1_0 := 1 To 3
  conout("linha")
Next

s_1_1 := contaLinhas(oDoc)
For s_1_0 := 1 To s_1_1
  nTotal := nTotal + 1
Next
```

Uma contagem literal vai direto para o cabeçalho. Qualquer outra coisa é ligada
antes, para que uma chamada fique acima do laço em vez de dentro dele. O
contador é um local de bloco oculto, com reciclagem de slot como qualquer outro.

### `do case with`

O `Do Case` do AdvPL fica intocado. A cláusula opcional `with` avalia o sujeito
uma vez e lhe dá um nome — a única coisa que o `Do Case` puro não faz, já que
todo `Case` repete a expressão.

```xtpl
do case with local nSub := calcTotal(n)
  case nSub == 6
    c := "seis"
  case nSub > 3
    c := "maior"
  case estaPronto(nSub)
    c := "pronto"
  otherwise
    c := "pequeno"
endcase
```

```advpl
s_1_0 := calcTotal(n)
Do Case
  case s_1_0 == 6
  ...
endcase
```

As condições são AdvPL comum, então não há nada novo para ler. Com `local` o
sujeito é um local de bloco novo — com escopo, reciclagem de slot, e pode levar
`<const>`. Sem ele, o sujeito atribui a uma variável declarada antes:

```xtpl
do case with nOutro := calcOutro(n)
```

### `with object`

Para código que repete o mesmo sujeito em toda linha — trabalho com FWModel, na
maior parte. O sujeito é avaliado uma vez e ligado; dentro do bloco, um `:`
inicial significa "o sujeito".

```xtpl
with object oModel:GetModel("SA1DETAIL")
  :SetValue("A1_COD", cCod)
  :SetValue("A1_NOME", cNome)
  cNome := :GetValue("A1_NOME")
end with
```

```advpl
s_1_0 := oModel:GetModel("SA1DETAIL")
s_1_0:SetValue("A1_COD", cCod)
s_1_0:SetValue("A1_NOME", cNome)
cNome := s_1_0:GetValue("A1_NOME")
```

`oModel:GetModel(...)` roda uma vez, e não uma vez por linha, o que é tão
importante quanto a brevidade.

Um `:` que vem depois de um nome, `)` ou `]` é acesso a membro comum e fica
intocado, assim como `::` para self e `:=` para atribuição. O que é substituído
é um dois-pontos numa posição onde o AdvPL não poderia tê-lo colocado. Os blocos
aninham — o sujeito mais interno vence, e o externo volta a valer no seu
`end with`.

O portador é um local de bloco comum, então recicla slot como qualquer outra
coisa.

### `using alias` — uma área de trabalho com escopo

Seleciona um alias, opcionalmente define uma ordem de índice, e devolve o que
encontrou em **toda** saída do bloco — inclusive um `return` antecipado.

```xtpl
using alias SA1 order 1 do
  nTotal := SA1->A1_SALDO
  return nTotal if nTotal > 100
end using
```

```advpl
s_1_0 := Alias()
DbSelectArea("SA1")
s_1_1 := SA1->(RecNo())
s_1_2 := SA1->(IndexOrd())
SA1->(DbSetOrder(1))
  nTotal := SA1->A1_SALDO
  If nTotal > 100
    SA1->(DbSetOrder(s_1_2))
    SA1->(DbGoto(s_1_1))
    If !Empty(s_1_0)
      DbSelectArea(s_1_0)
    EndIf
    Return nTotal
  EndIf
SA1->(DbSetOrder(s_1_2))
SA1->(DbGoto(s_1_1))
If !Empty(s_1_0)
  DbSelectArea(s_1_0)
EndIf
```

Esquecer de restaurar um alias é um bug clássico de Protheus, e o estrago
aparece em um lugar completamente diferente — que é justamente o que torna o
`return` antecipado o caso que vale a pena tratar. O ponteiro de registro também
volta: um percurso dentro do bloco deixa a área em `Eof`, e quem chamou não
pediu isso.

`order` é opcional, e a ordem de índice só é salva e restaurada quando é
informada.

Uma palavra solta é o próprio alias, já que `using alias SA1` é como se lê. Uma
variável em escopo contém um, em vez disso:

```xtpl
using alias SA1 do          // o alias
using alias cAlias do       // uma variável que contém um
```

Os blocos aninham, e cada um guarda seu próprio estado. Isso divide a mesma
maquinaria do `defer`, então os dois combinam a ordem em um `return`: **os
comandos adiados primeiro**, já que podem ainda querer a área, depois as áreas
de trabalho, do bloco mais interno para fora.

Os portadores são locais de bloco comuns, então reciclam slot como qualquer
outra coisa.

### `defer`

Registra um comando para rodar antes de toda saída da função, na ordem inversa
do registro.

```xtpl
defer fechaCursor()
defer registraSaida("terminado")
```

Emitido antes de cada `return` explícito e no fim natural do corpo.

O corpo é um comando comum e passa pelas mesmas etapas de qualquer outra linha,
então uma cadeia, uma leitura de hash ou um `xconout` dentro dele é traduzido.
Um corpo que vira vários comandos permanece junto onde quer que seja inserido:

```xtpl
defer aLinhas |> valida() |> grava()
```
```advpl
__pipe_tmp_0_0 := valida(aLinhas)
grava(__pipe_tmp_0_0)
```

Os nomes são resolvidos onde o `defer` é escrito, não onde ele roda, então os
dois caminhos de saída emitem a mesma coisa — e uma variável lida apenas por um
defer conta como lida.

Uma variável que um `defer` usa é fixada, como uma capturada por um code block:
o defer roda depois do bloco ter acabado, então o slot não pode ser reciclado
no meio-tempo.

### Modificadores posfixados

```xtpl
lFeito := .T. if nTotal > 5
exec limpaTudo() if nTotal == 0
conout("contando") while nTotal < 0
return nTotal if nTotal > 100
```

Um `return` posfixado roda os defers pendentes primeiro.

---

## Hashes

Dicionários sobre `THashMap`, sem a cerimônia de `Set`/`Get`.

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

**Chaves indexam um hash, colchetes indexam um array** — a separação do Perl.
Um `{` logo depois de um nome é acesso a hash, coisa que o AdvPL nunca tem,
então os dois se distinguem pela sintaxe e nenhum rastreamento de tipo é
necessário. Um grupo de chaves cujas partes de primeiro nível são todas
`k => v` é um literal de hash; qualquer outra coisa é um array. `{=>}` é o hash
vazio.

A leitura é içada para um comando, já que `Get` não é uma expressão. O
temporário é limpo antes porque `Get` deixa a variável intocada quando a chave
não existe, então uma chave ausente é lida de volta como `Nil`. `has` aproveita
o retorno lógico do `Get`, então o teste de existência não custa nada a mais.

`Clean()` não é gerado — é uma conveniência, não uma obrigação.

### Percorrendo um hash

`for` percorre arrays, então um hash não podia ser iterado de forma alguma.
`keys`, `values` e `pairs` devolvem arrays, então todo o resto se compõe com
eles sem mudança:

```xtpl
for cChave in keys(hCfg)
  conout("${cChave} = ${hCfg{cChave}}")
next

nTotal := values(hSaldos) |> asum
aMv    := keys(hCfg) |> filter([k] starts(k, "MV_"))
cLista := keys(hCfg) |> sort |> join(", ")
```

`pairs` mantém os dois juntos, uma linha `{chave, valor}` por entrada.

Eles passam por `THashMap:List(@aSaida)`, que preenche
`{{chave, valor}, ...}` e constrói o array inteiro — um hash está
em memória e é finito, então não há nada para transmitir sob demanda e nenhuma
razão para serem fontes como `rows` e `lines`.

**A ordem é a que o hash devolver.** Nada aqui ordena, porque a maioria dos
usos não precisa e `|> sort` está ali para quem precisa.

## Arrays

### Funções de array

Chamadas comuns, coleção primeiro, no mesmo formato de `aEval` e `aScan`. Um
lambda é `[apelido] corpo`, com até seis nomes — `[acc, x] corpo` para
`reduce`, `[a, b, c]` para um `zip` de três.

```xtpl
aVals  := map(aPedidos, [o] o:nValor)
aBig   := filter(aPedidos, [o] o:nValor > 1000)
aVivos := reject(aPedidos, [o] o:lCancelado)
nTotal := reduce(aNums, [acc, x] acc + x, 0)
aTop   := sortBy(aPedidos, [o] o:nValor, .T.)
```

O conjunto completo, todo ele em `xtpl_runtime.tlpp`:

| | |
|---|---|
| `map`, `filter`, `reject` | transformar, manter, descartar |
| `reduce(a, bloco, semente)` | dobra com semente explícita |
| `fold(a, bloco)` | dobra a partir do primeiro elemento; `Nil` se vazio |
| `take`, `drop` | os primeiros *n* ou todos menos os primeiros *n* |
| `asum`, `aprod`, `amax`, `amin` | dobra com operador fixo |
| `in(x, a)` | pertinência, por trás do operador `in` |
| `sort(a [, cmp])` | ordem natural, ou um comparador de dois elementos |
| `sortBy(a, chave [, lDesc])` | por uma chave extraída, ascendente salvo indicação |
| `distinct`, `distinctAdjacent` | duplicatas em qualquer lugar, ou apenas adjacentes |
| `reverse`, `flatten` | `flatten` é recursivo |
| `enumerate` | pares `{índice, valor}` |
| `chunks`, `chunkby` | blocos de tamanho fixo, ou por chave |
| `first`, `count` | o primeiro que casa; quantos casam |
| `maxby`, `minby` | o maior/menor **elemento** por uma chave |
| `anyof`, `allof`, `noneof` | algum, todos, nenhum |
| `scan`, `expand`, `tap`, `pairwise` | ver [as etapas de fluxo](#scan-expand-tap-e-pairwise) |
| `takewhile`, `dropwhile` | enquanto a condição valer, do início |
| `split`, `join`, `starts`, `ends`, `contains` | strings |
| `keys`, `values`, `pairs` | hashes |
| `zip(a, b, ... [, bloco])` | de dois a seis arrays, até o mais curto |

`zip` aceita de dois a seis arrays, e trata um code block em qualquer posição de
argumento como o combinador. Comprimentos diferentes são cortados
silenciosamente, como em Raku.

`sort` e `sortBy` copiam antes de ordenar. `aSort` trabalha no lugar, então sem
a cópia eles reordenariam o array de quem chamou — e, dentro de uma cadeia
`|>`, o array que alimenta a etapa. Toda função aqui devolve um array novo e
deixa sua entrada em paz.

Cada uma compila para um nome com prefixo `u_xtpl_`, o que as mantém longe de
uma função de mesmo nome já existente na base — mas isso também significa que
uma chamada à *sua* `take()` será redirecionada para a do runtime. Renomeie a
sua, ou tire o nome de `runtime_verbs`.

### Dobras

`asum`, `aprod`, `amax` e `amin` reduzem um array a um valor. `fold` cobre
qualquer outro caso.

```xtpl
nTotal := asum(aNums)
nMax   := amax(aNums)
cMaior := fold(aNomes, [acc, x] Iif(len(x) > len(acc), x, acc))
```

O prefixo `a` segue `aScan` e `aSort`, e mantém `amax`/`amin` longe dos `Max` e
`Min` de dois argumentos do próprio AdvPL, que um `max` simples teria capturado
em toda chamada existente.

`asum` e `aprod` começam de 0 e 1, então são seguros em um array vazio. `amax`,
`amin` e `fold` começam do primeiro elemento e devolvem `Nil` quando não há nada
para dobrar.

Sendo chamadas comuns, elas encadeiam:

```xtpl
nTotal := aPedidos |> filter([o] o:lPago) |> map([o] o:nValor) |> asum
```

### `in` — pertinência

```xtpl
if cCodigo in aCodigos
if nValor in 1..100
```
```advpl
If u_xtpl_in(cCodigo, aCodigos)
If (nValor >= 1 .And. nValor <= 100)
```

O `$` do AdvPL procura apenas em string, então um array precisa de `aScan`. Uma
faixa são duas comparações e não precisa de runtime nenhum.

A coleção termina na primeira vírgula, colchete ou `.and.` / `.or.` **no mesmo
nível**, então `f(cCod in aCodigos, nValor)` se lê como um teste de pertinência
e mais um argumento, enquanto `nValor in {1, 2, 3}` mantém seu literal inteiro.

### `%%` — divisível por

```xtpl
if nValor %% 3
if (nValor + 1) %% 3
```
```advpl
If (nValor % 3) == 0
If ((nValor + 1) % 3) == 0
```

O `%` sozinho é o módulo do próprio AdvPL e passa intocado.

### Uma cadeia não aninha, mas os verbos são funções comuns

Uma cadeia `|>` não pode ficar dentro de um lambda — içar as etapas para fora
do bloco as faria rodar antes dele, e não há lugar certo para pô-las. Mas todo
verbo de cadeia também é uma função comum, e chamá-la direto dentro do lambda
funciona:

```xtpl
|> filter([a] len(a) == 3 .and. allof(a, ehNumero))
|> map([a] asum(map(a, val)) / 3)
```

Na prática isso quase sempre dispensa a função auxiliar que a restrição
parece exigir.

### `lo..hi` como fonte

Um intervalo pode encabeçar uma cadeia, com a mesma grafia que `in 1..100`
usa. É a única fonte que percorre sem uma coleção atrás dela: o laço conta, e
nada é alocado.

```xtpl
nEuler := 1..999 |> filter([x] x %% 3 .or. x %% 5) |> asum
```

```advpl
fout_0_0 := 0

For fi_0_0 := 1 To 999
  fv_0_0 := fi_0_0
  If (fv_0_0 % 3) == 0 .or. (fv_0_0 % 5) == 0
    fout_0_0 := fout_0_0 + fv_0_0
  EndIf
Next
```

Pontas literais entram direto no cabeçalho; qualquer outra coisa é ligada
antes do laço, para uma chamada não ficar dentro dele. Como toda fonte, um
`take` interrompe o percurso — `1..1000000 |> filter(...) |> take(4)` não
conta até um milhão.

### `|>` — alimentação

Açúcar para encadeamento: o valor da esquerda vira o **primeiro argumento** da
etapa à direita. Essa é a única regra — ela não sabe nada sobre as funções
acima, então compõe tanto essas quanto os seus próprios auxiliares do mesmo
jeito.

```xtpl
aCodigos := aPedidos |> filter([o] o:nValor > 1000) |> map([o] o:cCodigo)
aCodigos := aPedidos |> meuAuxiliar(3) |> ordenaLinhas
```

```advpl
__pipe_tmp_0_1 := u_xtpl_filter(aPedidos, {|b_0_o| b_0_o:nValor > 1000})
__pipe_tmp_0_2 := u_xtpl_map(__pipe_tmp_0_1, {|b_0_o| b_0_o:cCodigo})
aCodigos := __pipe_tmp_0_2

__pipe_tmp_0_3 := meuAuxiliar(aPedidos, 3)
__pipe_tmp_0_4 := ordenaLinhas(__pipe_tmp_0_3)
aCodigos := __pipe_tmp_0_4
```

Cada etapa cai em seu próprio temporário, então nada é avaliado duas vezes.
Esses temporários são agrupados por comando — vivem exatamente uma linha, então
os nomes se repetem ao longo da função.

Uma cadeia executada pelos efeitos não precisa de resultado. Sem atribuição nem
`return` na frente, a última etapa é um comando por si só:

```xtpl
aPedidos |> valida() |> grava()
```
```advpl
__pipe_tmp_0_0 := valida(aPedidos)
grava(__pipe_tmp_0_0)
```

Uma cadeia sem atribuição não tem resultado a construir, e por isso **se funde
sem acumulador** — vira exatamente o laço que alguém escreveria à mão:

```xtpl
aCobertura |> filter([r] upper(r[1]) == cAlvo) |> tap([r] VarInfo("COBERTURA", r))
```
```advpl
fsrc_0_0 := aCobertura
For fi_0_0 := 1 To Len(fsrc_0_0)
  fv_0_0 := fsrc_0_0[fi_0_0]
  b_0_r := fv_0_0
  If upper(b_0_r[1]) == cAlvo
    b_0_r := fv_0_0
    VarInfo("COBERTURA", b_0_r)
  EndIf
Next
```

Vale também sobre uma fonte: `rows("SA1") |> tap([r] conout(r:A1_COD))` percorre
a tabela sem construir nada.

Uma cadeia dentro de uma expressão é içada para o seu próprio comando primeiro,
então compõe em qualquer lugar. Uma etapa isolada não precisa de temporário
próprio — a chamada em que ela vira já é uma expressão, e fica onde estava:

```xtpl
nTotal := len(aNums |> distinct)
nTotal := aNums |> filter([x] x > 100) |> asum
```
```advpl
nTotal := len(u_xtpl_distinct(aNums))

__pipe_tmp_0_0 := u_xtpl_filter(aNums, {|b_0_x| b_0_x > 100})
nTotal := u_xtpl_asum(__pipe_tmp_0_0)
```

O içamento é limitado pelos colchetes e vírgulas ao redor da cadeia, então uma
cadeia em um argumento não arrasta os outros junto. Isso vale também quando há
uma cadeia no nível de fora: em
`a |> take(len(b |> distinct))` a de dentro é içada primeiro.

**Não dentro de um code block.** O corpo de um bloco roda depois; içar uma
etapa para fora dele a faria rodar agora, e não há lugar correto para colocá-la
no lugar.

```xtpl
aOut := map(aNums, [x] x |> triplica)     // ERRO
```

> `Line 3: '|>' cannot chain inside a code block -- lifting its stages out would run them before the block does.`

Escreva a etapa como uma chamada aninhada comum — `[x] triplica(x)` — ou
encadeie sobre o array inteiro em vez de dentro do lambda.

### Fusão

Uma cadeia é uma chamada por etapa, e cada chamada percorre sua entrada e
constrói um array novo. Três etapas sobre um array grande são três laços e dois
arrays jogados fora. Onde as etapas olham um elemento de cada vez, elas são
emitidas como o corpo de um **único laço**.

```xtpl
aTop := aLinhas |> filter([r] r:nSaldo > 0) |> map([r] r:cCod) |> take(10)
```

```advpl
fsrc_0_0 := aLinhas
fout_0_0 := {}
fn_0_0 := 0
For fi_0_0 := 1 To Len(fsrc_0_0)
  fv_0_0 := fsrc_0_0[fi_0_0]
  b_0_r := fv_0_0
  If b_0_r:nSaldo > 0
    b_0_r := fv_0_0
    fv_0_0 := b_0_r:cCod
    If fn_0_0 >= 10
      Exit
    EndIf
    fn_0_0 := fn_0_0 + 1
    AAdd(fout_0_0, fv_0_0)
  EndIf
Next
aTop := fout_0_0
```

Nenhum array entre as etapas, e `take` é um `Exit` em vez de uma função que
roda depois de tudo já ter sido calculado — então o laço para em dez em vez de
percorrer o resto.

Um filtro vira um `If` aninhado, e não um `Loop` no começo do corpo. Isso é
necessário e não estético: sobre uma fonte que precisa avançar ao fim de cada
volta, um `Loop` pularia o avanço e travaria o laço.

`map`, `filter`, `reject`, `take`, `drop`, `takewhile`, `dropwhile`,
`distinctAdjacent`, `scan`, `expand`, `tap` e `pairwise` se fundem. `asum`,
`aprod`, `amax`, `amin`, `join`, `reduce`, `fold`, `chunkby`, `first`, `count`,
`maxby`, `minby`, `anyof`, `allof` e `noneof` se fundem como etapa final.

Um lambda precisa estar escrito na etapa — um code block guardado em uma
variável não pode ser embutido, e a cadeia volta para as chamadas de runtime.

**Só a sequência inicial.** `sort` não consegue produzir nada antes de ter visto
o último elemento; `distinct` precisa lembrar do que já viu. Essas e as demais
seguem como etapas comuns, a partir do array que o laço construiu, e o xtpl
avisa:

```
warning: line 31: 'sort' cannot be fused -- it needs the whole collection, so it and every stage after it builds an array
```

**Toda cadeia que não se funde é relatada**, com a razão certa para cada caso:

```
warning: line 3: this chain does not fuse -- 'sort' stops it, because it needs the whole collection, so it and every stage after it builds an array
warning: line 10: this chain does not fuse -- 'meuAuxiliar' stops it, because xtpl cannot see inside it, so it and every stage after it builds an array
```

Um verbo do runtime que precisa da coleção inteira é uma coisa; uma função sua,
que o xtpl nunca viu, é outra.

**Uma etapa isolada continua sendo uma chamada.** Uma etapa é um laço de
qualquer forma, então fundi-la só deixaria a saída mais longa.

### `takewhile` e `dropwhile`

`filter` mantém toda ocorrência, em qualquer lugar. `takewhile` mantém a
sequência que casa no início e **para na primeira que não casa** — não olha o
resto.

```xtpl
aFrente := aLinhas |> takewhile([r] r:nSaldo > 0)
```

Sobre uma fonte ordenada é justamente esse o ponto: uma vez que a chave muda,
sabe-se que o resto não casa, então ler adiante não ensinaria nada.

`dropwhile` é o espelho — pula a sequência inicial e depois deixa passar tudo,
inclusive elementos que teriam casado. Por isso ele precisa de um sinalizador,
e não de um teste.

**Dê uma chave ao `rows` e ele posiciona em vez de começar do topo**, que é o
que torna `takewhile` valioso numa tabela grande — chegar ao grupo em um salto,
e então parar no fim dele:

```xtpl
using alias SC6 order 1 do
  aItens := rows("SC6", xFilial("SC6") + cNum) ;
            |> takewhile([r] r:C6_NUM == cNum) ;
            |> map([r] r:C6_PRODUTO)
end using
```

O `DbSeek` usa a ordem de índice que estiver definida, então `using alias ...
order N` em volta da cadeia é como ter certeza de qual. Um seek que não acha
nada cai em `Eof`, então o percurso não produz nada — nenhum teste próprio é
necessário.

Vale lembrar que o `DbSeek` casa por prefixo: se a chave não estiver
preenchida na largura do campo, `"1"` também casa com `10` e `100`. O
`takewhile` faz trabalho de verdade ali, não apenas encerra o grupo.

Sem chave ele ainda começa do topo, e as duas etapas se compõem para alcançar
um grupo lendo em vez de posicionando:

```xtpl
aGrupo := rows("SC6") |> dropwhile([r] r:C6_NUM != cNum) |> takewhile([r] r:C6_NUM == cNum)
```

Correto, e nunca lê além do grupo — mas chega até ele varrendo.

### Etapas finais

`join` é o único terminal *nomeado* que recebe um argumento. Um sinalizador
marca o primeiro elemento, em vez de testar se o acumulador está vazio, o que
perderia o separador depois de um primeiro elemento legitimamente vazio.

```xtpl
cLista := aLinhas |> map([r] r:cCod) |> join("; ")
```

**`reduce` e `fold` também se fundem**, e são a razão de os terminais fundíveis
não serem uma lista fechada de nomes. Eles carregam seu próprio passo de
combinação, então o transpilador não precisa saber nada de antemão — uma
agregação sua se funde exatamente como uma embutida:

```xtpl
cLista := aLinhas |> map([r] r:cCod) |> reduce([acc, x] acc + "; " + x, "")
cLongo := aLinhas |> map([r] r:cNome) |> fold([acc, x] Iif(len(x) > len(acc), x, acc))
```

A semente é avaliada uma vez, antes do laço. `fold` é a forma sem semente: o
primeiro elemento é o valor inicial, então fica `Nil` até que um chegue.

Um terminal não precisa ser a última etapa. `chunkby` devolve um array de
grupos, e o resto da cadeia segue a partir dele.

### `scan`, `expand`, `tap` e `pairwise`

**`scan`** é o `reduce` que mostra a conta — o acumulador depois de cada
elemento, e não só do último. Um saldo acumulado é a razão de existir:

```xtpl
aSaldos := aMovs |> map([m] m:nValor) |> scan([acc, x] acc + x, 0)
```

Movimentos `{100, -30, 50}` dão `{100, 70, 120}`, onde `reduce` daria `120`. O
valor corrente segue cadeia abaixo, então
`|> scan(...) |> filter([s] s < 0)` acha todo ponto em que o saldo ficou
negativo.

**`expand`** transforma um elemento em quantos o bloco devolver — o inverso do
`filter`, que transforma um em zero ou um:

```xtpl
aProdutos := rows("SC5") |> expand([r] itensDoPedido(r:C5_NUM)) |> map([i] i:cProduto)
```

Para cada pedido, seus itens, e a cadeia segue com os **itens**. Vira um laço
dentro do laço, então nada é materializado — `map` seguido de `flatten`
construiria toda lista de itens antes de achatar qualquer uma.

**`tap`** roda um bloco pelo efeito e devolve o elemento intocado, para que uma
cadeia possa ser observada sem ser desmontada:

```xtpl
aCodigos := aLinhas |> filter([r] r:nSaldo > 0) |> tap([r] conout(r:cCod)) |> map([r] r:cCod)
```

**`pairwise`** dá cada elemento junto com o anterior. O primeiro não tem
antecessor, então *n* elementos dão *n-1* pares:

```xtpl
aDeltas := aLeituras |> map([l] l:nMedidor) |> pairwise |> map([p] p[2] - p[1])
```

`scan` e `pairwise` precisam de um valor para carregar, então sobre `rows`
querem um `map` antes. `tap` e `expand` leem o registro e não precisam.

### `distinctAdjacent` — e como difere de `distinct`

Dois nomes, dois algoritmos, e são os nomes que esses algoritmos têm em outros
lugares.

| | compara contra | passagens | funde |
|---|---|---|---|
| `distinct` | tudo que já foi guardado | O(n²) | não |
| `distinctAdjacent` | apenas o elemento anterior | O(n) | sim |

`distinctAdjacent` compara cada elemento com o imediatamente anterior, então
descarta sequências repetidas. `distinct` compara com tudo que já guardou,
então descarta duplicatas em qualquer lugar. **Sobre entrada não ordenada os
dois dão respostas diferentes**, então a escolha não é questão de gosto.

Ele não exige entrada ordenada, e não verifica isso — entrada ordenada é o caso
comum, não uma pré-condição. Colapsar sequências repetidas numa série
cronológica, para achar onde um valor mudou, é um uso igualmente bom.

```xtpl
aPedidos := aLinhas |> map([r] r:cPedido) |> distinctAdjacent
```

Com uma chave ele compara essa chave em vez do elemento — o que, sobre uma
tabela ordenada, dá os valores distintos de um campo em uma passagem:

```xtpl
using alias SC6 order 1 do
  aNumeros := rows("SC6") |> distinctAdjacent([r] r:C6_NUM) |> map([r] r:C6_NUM)
end using
```

Sem chave, sobre `rows` não há o que comparar, já que um registro não é um
valor, e o uso é recusado.

### `maxby` e `minby`

O maior **elemento** por uma chave extraída, onde `amax` dá a maior chave e
perde a linha de onde ela veio:

```xtpl
nMaior := aLinhas |> map([r] r:nValor) |> amax      // 15000
oMaior := aLinhas |> maxby([r] r:nValor)           // a linha que vale 15000
```

Sem eles você ordena tudo para olhar um só — e `sort` bloqueia a fusão, então
isso ainda constrói um array intermediário.

### `first` e `count`

`first` dá o primeiro que casa e para ali. `count` diz quantos casam sem
construir o array deles.

```xtpl
oAtrasado := aLinhas |> map([r] r:oPed) |> first([p] p:lAtraso)
nGrandes  := aLinhas |> map([r] r:nValor) |> count([v] v > 100)
```

Os dois substituem `filter(...)` seguido de olhar o resultado — o que constrói
um array para responder uma pergunta que não precisa de um, e, no caso do
`first`, continua procurando depois que a resposta já é conhecida. `first`
devolve `Nil` quando nada casa.

`count` sem condição conta o que chega até ele, que é como medir um percurso
sobre algo que não tem comprimento até ter sido lido:

```xtpl
using alias SC6 order 1 do
  nItens := rows("SC6", xFilial("SC6") + cNum) |> takewhile([r] r:C6_NUM == cNum) |> count
end using
```

`count` lê o elemento, então sobre `rows` não precisa de `map` antes. `first`
precisa: ele devolve o elemento, e um registro de área de trabalho não é um
valor.

### `chunkby`

Agrupa elementos **consecutivos** que compartilham uma chave — um array por
grupo, em uma passagem, mantendo um grupo por vez.

```xtpl
using alias SC6 order 1 do
  aGrupos := rows("SC6", xFilial("SC6") + cNum) ;
             |> map([r] {r:C6_NUM, r:C6_PRODUTO}) ;
             |> chunkby([x] x[1])
end using
```

Esse é o percurso cabeçalho/itens, que de outro modo é um laço aninhado com um
teste de `Eof()` interno fácil de errar.

**Consecutivos é a palavra que importa.** Ele corta a sequência onde a chave
muda; não junta ocorrências espalhadas. Sobre entrada não ordenada a mesma chave
volta mais de uma vez. Isto não é `GROUP BY` — e é exatamente isso que permite
transmitir sob demanda.

Sobre uma área de trabalho, o bloco da chave lê o valor que um `map` produziu, e
não o registro, já que depois de um map o elemento é aquilo que o map fez dele.

### Predicados

`anyof`, `allof` e `noneof` perguntam se os elementos casam, e **param assim
que sabem**:

```xtpl
lAtraso  := aLinhas |> anyof([r] !r:lPago)
lTodosOk := aLinhas |> map([r] r:nValor) |> allof([v] v > 0)
```

Sem eles a pergunta exige um array filtrado e um `len()`, o que lê a coleção
inteira para responder algo geralmente resolvido pelo primeiro elemento.

Eles leem o elemento e não um valor feito dele, então sobre uma área de trabalho
nenhum `map` é necessário antes — e o próprio percurso para:

```xtpl
lNegativo := rows("SA1") |> anyof([r] r:A1_SALDO < 0)
```

sai da tabela no primeiro saldo negativo em vez de ler até o `Eof`.

### Fontes

`rows` e `lines` são **fontes**, não funções. Uma fonte é algo a percorrer, e
aparece em exatamente dois lugares:

```xtpl
aCodigos := rows("SA1") |> map([r] r:A1_COD)     // no início de uma cadeia
for cLinha in lines(cCaminho)                    // como origem de um 'for'
```

**Uma fonte não é um valor.** Não pode ser atribuída a algo e usada depois,
passada para uma função, nem guardada — não há o que guardar, porque uma fonte
é percorrida e não produzida. Em qualquer outro lugar ela é recusada:

```xtpl
nQuantas := len(lines(cCaminho))     // ERRO
```

> `Line 11: 'lines()' is a source, and only reads at the head of a chain. Assign it, or feed it into stages with '|>'.`

Essa é a regra inteira, e as restrições de cada fonte abaixo decorrem dela, em
vez de serem regras separadas a decorar.

**Rodar o percurso até o fim é a exceção.** Uma cadeia sem etapas não tem para
onde transmitir, então constrói o array:

```xtpl
aTodas := lines(cCaminho)            // toda linha
```

`rows` não faz isso, por um motivo próprio: um registro de área de trabalho não
é um valor, então não há o que coletar sem um `map` antes.

As fontes recebem nomes de substantivos no plural, pelo que produzem. `items`
está reservado para uma terceira, sobre qualquer objeto que possa ser
percorrido; ela ainda não existe.

**Por que a restrição existe.** Aqui a preguiça é uma propriedade de tempo de
compilação, não de execução. Não há objeto carregando um iterador — o
transpilador escreve um laço com as etapas dentro, o que só consegue fazer
quando enxerga o pipeline inteiro em um comando. O `lines` do Raku pode ser
guardado numa variável porque o runtime dele tem um protocolo de iteração; o
AdvPL não tem, e construir um significaria um `Eval` por elemento por etapa e
uma saída que não se parece mais com o que foi escrito.

### `rows` — uma área de trabalho como fonte

Uma área de trabalho já é uma sequência preguiçosa com uma convenção de chamada
desajeitada: `DbGoTop()` inicia, `Eof()` testa, `DbSkip()` avança. `rows` lhe dá
o mesmo formato de um array, e a cadeia se funde ao percurso — então a tabela é
lida um registro por vez e nunca carregada.

```xtpl
nTotal := rows("SA1") |> filter([r] r:A1_SALDO > 0) |> map([r] r:A1_VALOR) |> asum
```

```advpl
farea_0_0 := Alias()
DbSelectArea("SA1")
frec_0_0 := SA1->(RecNo())
SA1->(DbGoTop())
fout_0_0 := 0
While !SA1->(Eof())
  If SA1->A1_SALDO > 0
    fv_0_0 := SA1->A1_VALOR
    fout_0_0 := fout_0_0 + fv_0_0
  EndIf
  SA1->(DbSkip())
EndDo
SA1->(DbGoto(frec_0_0))
If !Empty(farea_0_0)
  DbSelectArea(farea_0_0)
EndIf
nTotal := fout_0_0
```

A área selecionada e o ponteiro de registro são devolvidos depois. Deixar um
alias em outro lugar é um bug clássico de Protheus, cujo estrago aparece em
código que não tinha nada a ver com a linha.

`rows(alias, chave)` posiciona em vez de ir ao topo; veja
[takewhile](#takewhile-e-dropwhile).

Um alias literal é escrito por extenso, já que `SA1->A1_COD` é o que um
desenvolvedor Protheus lê. Qualquer outra coisa é ligada uma vez e alcançada
pela forma entre parênteses do AdvPL, `(cAlias)->A1_COD`.

**O elemento é o registro, não um valor.** `r:A1_COD` compila para uma
referência de campo; o nome não pode ser usado para mais nada, porque não há
objeto a passar:

```xtpl
rows("SA1") |> filter([r] estaOk(r))     // ERRO
```

> `Line 4: over rows() the element is the current record, not a value, so it can only be used to name a field.`

E uma cadeia precisa dar `map` do registro para um valor antes que se possa
coletar qualquer coisa — não há mais nada a coletar.

Suas etapas precisam ser das que se fundem ao percurso. `sort` e `distinct` não
se fundem, e um `take` depois delas já não interromperia a varredura.

### `lines` — um arquivo como fonte

O mesmo protocolo do `rows`, sobre texto. `FT_FUse` abre o arquivo,
`FT_FReadLn` lê uma linha, `FT_FSkip` avança, `FT_FUse()` fecha — o idioma que
o Protheus já usa, então o arquivo nunca fica em memória e um `take` de fato
interrompe a leitura.

```xtpl
aTop := lines("dados.txt") |> filter([l] !empty(l)) |> map([l] alltrim(l)) |> take(10)
```

```advpl
fsrc_0_0 := "dados.txt"
FT_FUse(fsrc_0_0)
FT_FGoTop()
fn_0_0 := 0
fout_0_0 := {}
While !FT_FEof()
  fv_0_0 := FT_FReadLn()
  b_0_l := fv_0_0
  If !empty(b_0_l)
    b_0_l := fv_0_0
    fv_0_0 := alltrim(b_0_l)
    If fn_0_0 >= 10
      Exit
    EndIf
    fn_0_0 := fn_0_0 + 1
    AAdd(fout_0_0, fv_0_0)
  EndIf
  FT_FSkip()
EndDo
FT_FUse()
aTop := fout_0_0
```

Diferente do `rows`, aqui o elemento **é** um valor — a linha — então um
parâmetro de lambda se liga a ele da maneira comum.

**Como origem de `for`**, quando o corpo são comandos em vez de uma cadeia:

```xtpl
for cLinha, nNumero in lines(cCaminho)
  if empty(cLinha)
    loop
  endif
  return nNumero if cLinha == cProcurado
next
```

Isso funciona onde `for` sobre `rows` não funcionaria: aqui o elemento **é** um
valor, então se liga a um nome da maneira comum. Um registro de área de
trabalho não é um valor, e é por isso que o mesmo formato é recusado lá.

O arquivo avança logo depois que a linha é lida, e não no pé do laço, então um
`loop` no corpo é seguro. Um `return` antecipado fecha o arquivo na saída, do
mesmo modo que uma área de trabalho é restaurada.

**Sem etapas ainda é uma cadeia**, e lê todas as linhas:

```xtpl
aTodas := lines(cCaminho)
```

Uma etapa que não pode ser fundida encerra o percurso em vez de impedi-lo:
`lines(cCaminho) |> sort` coleta as linhas e as ordena, porque ordenar não pode
começar antes de a última linha ser conhecida.

Se o arquivo não abrir, o percurso não produz nada e o resultado fica vazio —
o laço testa `File()` além de `!FT_FEof()`, porque num arquivo que nunca abriu
`FT_FEof()` fica `.F.` e o laço não terminaria nunca.

**Só texto.** `FT_FReadLn` quebra em fim de linha e strings AdvPL são bytes,
então um arquivo binário não falha — ele é silenciosamente cortado a cada byte
0x0A, e qualquer que seja o comprimento máximo de linha da família FT_, isso
trunca um arquivo que não tem quebras de linha nenhuma, que é a cara de um
arquivo binário. Não há um `bytes(arquivo)` correspondente; para isso use
`FOpen` e `FRead` diretamente.

`lines` e `rows` são nomes de fonte, então essas duas palavras estão tomadas.

### `fallback`

Protege uma expressão: se ela levantar erro, devolve a alternativa. Funciona em
uma chamada simples, em um `return` ou em uma cadeia `|>` inteira.

```xtpl
e := chamadaArriscada(1) fallback "padrão"
n := aNums |> filter([x] x > 1000) |> asum fallback 0
```

```advpl
e := u_xtpl_safe_pipe({|| chamadaArriscada(1)}, {|| "padrão"})
```

Os dois lados são code blocks, então a alternativa só é avaliada quando o lado
protegido realmente falha. `u_xtpl_safe_pipe` troca o error block por um que
faz `Break` em erro de execução e o restaura depois, porque um `BEGIN SEQUENCE`
puro só captura `Break()`.

`fallback` é retirado da linha antes de qualquer outra reescrita, então tudo o
que a linha vier a gerar termina dentro da proteção. Eles viram expressões
separadas por vírgula dentro do bloco, o que mantém cada etapa avaliada uma vez
sem deixar nada fora da proteção.

**Sob uma guarda, uma cadeia não se funde, e o xtpl avisa.** O corpo de um code block são
expressões separadas por vírgula, e um laço fundido é `While`/`EndDo`, que não
é expressão. Uma cadeia sobre array volta às chamadas de runtime, que são
expressões. Uma fonte não tem forma sem fusão, então não pode ser protegida:

```xtpl
nTotal := rows("SA1") |> map([r] r:A1_SALDO) |> asum fallback 0     // ERRO
```

> `Line 10: 'fallback' cannot guard a walk over rows(). The guard needs an expression and a walk is a loop. Assign the chain first, then guard what uses it.`

Perder uma passagem é invisível no fonte, então é relatado:

```
warning: line 22: 'fallback' turns off fusion for this chain -- a guard needs an expression and a fused loop is not one, so each stage builds an array again. Guard the part that can fail instead, and leave the chain outside it.
```

Quase sempre é melhor proteger só a parte que pode falhar, e deixar a cadeia
fora da guarda. Uma guarda entre parênteses é içada para um comando próprio, e
a cadeia funde normalmente:

```xtpl
aLista := (chamadaArriscada(2) fallback {}) |> filter([x] x > 1) |> map([x] x * 2)
```
```advpl
__guard_tmp_0_0 := u_xtpl_safe_pipe({|| chamadaArriscada(2)}, {|| {}})
fsrc_0_0 := __guard_tmp_0_0
For ...
```

### Strings

O runtime carrega apenas o que falta ao AdvPL. `Upper`, `Lower`, `AllTrim`,
`PadL`, `PadR`, `StrTran` e as demais já recebem seu assunto primeiro, então
encadeiam como estão — e embrulhá-las sombrearia as originais em toda chamada
existente na base.

```xtpl
cOut := cNome |> alltrim |> upper          // as do próprio AdvPL, nada acrescentado
```

| | |
|---|---|
| `split(texto, sep)` | para um array, com separador de qualquer tamanho |
| `join(partes, sep)` | de volta para uma string |
| `starts(texto, o_que)`, `ends(texto, o_que)` | prefixo e sufixo |
| `contains(texto, o_que)` | o `$` se lê com a agulha primeiro, que é o jeito habitual de errar; este recebe o texto primeiro, como todo o resto |

### Interpolação

```xtpl
cMsg := "total = ${nTotal} itens"
```
```advpl
cMsg := ("total = " + cValToChar(nTotal) + " itens")
```

O literal vira uma concatenação antes de qualquer outra etapa vê-lo, então uma
expressão dentro dele é código comum — inclusive uma leitura de hash:

```xtpl
cMsg := "taxa ${hCfg{'t'}} fim"
```

**Uma expressão interpolada não pode usar a mesma aspa que delimita a string em
volta.** Os literais são mascarados antes de qualquer coisa rodar, então a aspa
de dentro encerra a string de fora:

```xtpl
cMsg := "taxa ${hCfg{"t"}} fim"      // ERRO
```

> `Line 9: '${' in a string is never closed. An interpolated expression cannot use the same quote as the string around it -- write '...' inside "...".`

### `xconout`

```xtpl
xconout("total=", nGrande, " itens")
```

```advpl
conout("total=" + cValToChar(nGrande) + " itens")
```

Literais de string passam direto; todo o resto é embrulhado em `cValToChar`.

## `queue`

Uma fila, primeiro a entrar, primeiro a sair. A única estrutura de dados que
valeu a pena acrescentar: arrays AdvPL já são dinâmicos, então uma pilha é
`AAdd` mais `ATail` mais `aSize`, mas tirar da **frente** significa `ADel` e
depois `aSize`, o que move todo elemento restante, uma vez por retirada. Esta é
um buffer circular, então uma retirada não move nada.

```xtpl
local oFila := queue()          // ou queue(256) para um tamanho inicial

for oPedido in aPedidos
  oFila:Push(oPedido)
next

while !oFila:IsEmpty()
  oProximo := oFila:Pop()
enddo
```

| | |
|---|---|
| `Push(x)` | acrescenta no fim |
| `Pop()` | tira da frente, `Nil` quando vazia |
| `Peek()` | a frente, sem tirar |
| `Count()`, `IsEmpty()` | quantos, e se há algum |

Ela dobra de tamanho quando enche, então o tamanho inicial é uma dica, não um
limite. `Pop()` devolve `Nil` numa fila vazia — pergunte `IsEmpty()` antes se
`Nil` for um valor que você possa legitimamente ter enfileirado.

A classe é `XtplQueue`, e esse nome está tomado, como os verbos do runtime.

## Removidos

| Era | Por quê | Agora |
|---|---|---|
| `let` | Duplicava `local` depois que `local` ganhou semântica de pilha | `local` |
| `gather` / `take` | Ansioso e léxico, então nada melhor que `aadd`; a versão útil precisa de escopo dinâmico | monte o array |
| `given` / `when` | Uma cadeia `if`/`elseif` com vocabulário novo. `Do Case` diz a mesma coisa em AdvPL que um desenvolvedor Protheus já lê; a única lacuna era nomear o sujeito, que `do case with` preenche | `do case with` |
| `?=>` | Encadeava como o operador de alimentação mas sem os verbos, e não fazia nada sem `fallback` | `\|>` mais `fallback` |
| `local x ?= v` | Um local recém-criado é sempre Nil, então o teste nunca falha | `local x := v` |
| `==>`, depois `=>` | Renomeado; `=>` colide com o separador do próprio pré-processador e com literais de hash | `\|>` |
| `Z` | Renomeado | `zip` |
| `with` / `orwith` / `without` | O resultado do teste nunca era ligado, então um ramo não podia usá-lo; `without x do` é apenas `If x == Nil` | `?:` para o primeiro não-Nil, `if` para o resto |
| `for each` | As três formas de `for` se distinguem pelo formato, então `each` não dizia nada — e tomava emprestada a grafia do Harbour para algo mais restrito | `for` |
| `uniq` | Renomeado; o nome corre o risco de ser lido como `distinct`, e os dois dão respostas diferentes | `distinctAdjacent` |

Cada um levanta um erro de migração nomeando o substituto, em vez de emitir
AdvPL inválido.

---

## Continuação de linha

Um `;` no fim junta uma linha com a seguinte, como no AdvPL. O comando é
processado como uma linha lógica só, então um operador pode ficar de qualquer
lado da quebra.

```xtpl
cResp := HttpPost(cUrl, "", cCorpo, nTimeout, ;
                  {"Content-Type: application/json"}) fallback ""
```

Os erros apontam a primeira linha do grupo.

O `;` é procurado além de um comentário final, então um comentário pode ficar em
uma linha continuada. Ele se move para o fim do comando já juntado, já que, uma
vez que as linhas viram uma só, não há outro lugar para ele.

## `raw` — entregar uma linha ao pré-processador

Um `#command` ou `#xtranslate` reescreve *sintaxe*, não identificadores. Então
uma linha como esta ainda não é AdvPL — só vira AdvPL depois que o
pré-processador roda, o que é depois do xtpl:

```xtpl
raw @ 10, 5 SAY "Total" GET nTotal PICTURE "@E 999,999.99"
```

`raw` diz: não tente entender esta linha. Há uma forma em bloco, para telas e
diálogos:

```xtpl
raw
  @ 12, 5 SAY "Nome" GET cNome PICTURE "@!"
  @ 14, 5 SAY "Obs"  GET cObs  SIZE 60, 10
end raw
```

**Variáveis declaradas continuam sendo renomeadas dentro de `raw`**, então
locais de bloco funcionam ali como em qualquer lugar. Só a verificação de nomes
não declarados é relaxada, porque `SAY`, `GET` e `PICTURE` são comandos, não
variáveis.

Uma variável mencionada em uma linha `raw` é fixada, do mesmo modo que uma
capturada por um code block. O transpilador não enxerga o que o comando faz com
ela, e `GET` em particular passa por referência a um diálogo que sobrevive ao
bloco.

## Includes

Todo arquivo gerado recebe, no topo:

```advpl
#include "totvs.ch"
#include "tlpp-core.th"
```

Só os que o fonte ainda não pediu — um arquivo que já inclui `totvs.ch` não
acaba com ele duas vezes.

## Codificação e fim de linha

O arquivo é lido como foi escrito. UTF-8, cp1252 ou ISO-8859-1 são detectados,
e a saída sai na mesma codificação e com o mesmo fim de linha — gravar UTF-8 a
partir de um fonte latin-1 corromperia toda string acentuada a caminho de um
compilador que não espera isso.

## Comentários

As duas formas do AdvPL funcionam. `/* ... */` é convertido para `//` antes de
qualquer outra coisa ler o arquivo, então um comentário em bloco pode conter o
que quiser — uma declaração, uma cadeia, uma chave desbalanceada — sem que nada
disso seja lido como código.

Um bloco que termina no meio de uma linha tem seu texto movido para o fim
daquela linha, já que `//` vai até o fim e não há outro lugar para ele:

```xtpl
nA := /* na linha */ nX + 1
```
```advpl
nA :=  nX + 1  // na linha
```

Os números de linha não mudam: nenhuma linha é acrescentada ou removida pela
conversão.

## Verificação de campos

Desligada, a menos que um dicionário seja informado. `SA1->A1_NMOE` quando o
campo é `A1_NOME` é um erro de execução hoje, invisível ao AdvPL e ao
pré-processador.

```
python3 xtpl_transpiler.py --dict sx3.csv pedido.xtpl pedido.tlpp
```

```
warning: line 22: 'SA1->A1_NMOE' is not a field of SA1. Did you mean A1_NOME?
warning: line 23: alias 'SAX' is not in the dictionary. A table that is missing usually means the export is out of date.
```

Os dois são relatados de formas diferentes de propósito: **um campo ausente
costuma ser erro de digitação, uma tabela ausente costuma ser exportação
desatualizada.** Um nome de campo parecido é sugerido quando existe.

Avisos por padrão, já que um campo recém-criado pode ainda não estar numa
exportação e um dicionário velho não deveria parar um build. `--dict-strict`
transforma os avisos em erros, para CI.

### Tipos e tamanhos

Onde a exportação traz `X3_TIPO` e `X3_TAMANHO`, um campo usado com um
**literal** do tipo errado é relatado, e também uma string grande demais para
caber:

```
warning: line 12: SA1->A1_NOME is character, assigned a numeric value.
warning: line 17: SA1->A1_SALDO is numeric, compared with a character value.
warning: line 31: SA1->A1_COD holds 6 characters, but is assigned 7.
```

Esse último é truncamento silencioso — o AdvPL grava o que cabe e descarta o
resto.

**Só literais têm tipo.** Um campo usado com uma variável é deixado em paz:

```xtpl
SA1->A1_COD := cQualquer          // nada é afirmado
```

Inferir tipos em uma linguagem sem tipos é como um verificador vira uma máquina
de falsos positivos. `Nil` também é deixado em paz, já que atribuí-lo é comum.
Uma exportação sem a coluna de tipo ainda dá a verificação de nomes.

O dicionário é uma exportação da SX3 em CSV. Os nomes de coluna variam entre
exportações, então as colunas de tabela e campo são encontradas pelo que os
cabeçalhos contêm — ARQUIVO, ALIAS, TABELA ou TABLE para uma, CAMPO ou FIELD
para a outra — e um arquivo sem cabeçalho reconhecível recai nas duas primeiras
colunas.

**As cadeias também são verificadas.** Um campo nomeado através de `rows` já
virou uma referência de campo comum quando é emitido:

```xtpl
aC := rows("SA1") |> map([r] r:A1_NMOE)     // pego
```

O que não pode ser verificado é um alias guardado em uma variável —
`rows(cAlias)` ou `(cAlias)->A1_COD` — já que o que ele contém não se sabe
aqui. Esses são pulados, e não adivinhados.

## `--map`

Toda linha emitida carrega a linha de origem de onde veio.

```
python3 xtpl_transpiler.py --map pedido.xtpl pedido.tlpp
```

```advpl
fsrc_0_0 := aNums  // xtpl:11
For fi_0_0 := 1 To Len(fsrc_0_0)  // xtpl:11
  fv_0_0 := fsrc_0_0[fi_0_0]  // xtpl:11
```

Uma linha de origem vira uma dúzia com frequência, então a marca vai em todas e
não só na primeira — procurar para cima a mais próxima é exatamente o trabalho
que isto existe para eliminar. Um erro de execução no `.tlpp` então se lê de
volta até o que foi escrito.

`compile_check.py` usa essas marcas para traduzir os erros do compilador de
volta para o fonte.

## `--check`

Analisa e relata, sem escrever nada. O caminho de saída passa a ser opcional.

```
python3 xtpl_transpiler.py --check --dict sx3.csv pedido.xtpl
```

Os avisos vão para stderr como de costume e o código de saída é 0; um erro sai
com 1. Com `--dict-strict` ao lado, um aviso de dicionário vira erro e faz o
processo falhar, que é o formato que a CI quer.

## Avisos

Uma declaração que a função nunca lê é relatada, distinguindo os dois erros:

```
warning: line 3: 'nEscrito' is assigned but never read
warning: line 4: 'nNuncaUsado' is declared but never used
```

O primeiro geralmente é sobra de uma edição ou um resultado que ninguém quis; o
segundo, um erro de digitação que criou uma segunda variável ou uma declaração
que sobreviveu ao seu uso. Os avisos vão para stderr e não param o build.

Parâmetros não são relatados — um parâmetro sem uso muitas vezes faz parte de
uma interface que precisa manter o formato.

## `--legacy`

Uma coisa impede o xtpl de aceitar um `.prw` existente: **uma escrita em um
nome não declarado.** O AdvPL permite e cria uma `PRIVATE` — um anti-padrão,
mas legal — enquanto o xtpl recusa. `--legacy` transforma isso em aviso.

Todo o resto que o xtpl verifica aqui, o AdvPL também verifica. **Ler** um
nome não declarado é erro no AdvPL igualmente, então isso não é uma restrição
do xtpl. Nem o prólogo: o AdvPL recusa um `Local` depois do primeiro comando, e
um `Local` dentro de um bloco, então nenhum arquivo que compila hoje tem
qualquer um dos dois. O prólogo é relaxado assim mesmo, como conveniência, e
relatado.

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

**O escopo fica intocado.** `local` com escopo de bloco é algo que o xtpl
acrescenta onde o AdvPL não tem nada, então não há significado existente a
preservar e nenhuma razão para desligá-lo. Uma declaração fora do prólogo
mantém seu inicializador onde foi escrito, já que dobrá-lo no `Local` içado o
faria rodar na entrada da função — outro programa.

Um nome não declarado é deixado exatamente como escrito e **não** é declarado
para você. Declará-lo acrescentaria um `Local` que o fonte nunca teve — e onde
a escrita cria uma `PRIVATE`, um `Local` nem seria a mesma coisa.

**Um nome que uma escrita trouxe à existência é relatado uma vez, onde
acontece.** As leituras depois dele são de uma variável que a essa altura
existe, então não são relatadas; uma leitura sem escrita antes ainda é, já que
o AdvPL também recusaria.

As contagens no fim são tão importantes quanto os avisos. `SAY`, `GET` e
`PICTURE` no topo dizem que o arquivo tem forma de comando e quer `raw`, não
declarações — que é como saber, antes de converter qualquer coisa, se um
arquivo vale a pena converter.

Todo o resto continua valendo: construções removidas ainda são erros, `<const>`
e `<contained>` continuam valendo, e a verificação de campos continua rodando.

## Retornar valor só em alguns caminhos

```
warning: line 14: this returns nothing, but the function returns a value on line 11
warning: line 24: the function can reach its end without a return, but returns a value on line 20
```

Quem chamou recebe `Nil` e descobre em outro lugar e mais tarde. O AdvPL não
diz nada a respeito.

## Forma da chamada

O compilador põe o `U_` na declaração de uma `User Function`, então ela é
alcançada como `u_nome`. Uma `Static Function` é chamada pelo nome simples.
Trocar os dois compila, linka, e só falha rodando — o xtpl confere contra a
declaração, nos dois sentidos:

> `Line 3: 'u_ajuda' -- ajuda is a static function in this file, so it is called by its plain name, without the 'u_'.`

Só para funções declaradas no mesmo arquivo: de outro arquivo não há como saber.

## Contagem de argumentos

Uma chamada a uma função declarada no mesmo arquivo é conferida contra a
assinatura dela. O AdvPL não confere nada disso.

> `Line 10: calcTotal() takes 2 parameters (line 4), but is given 3.`

**Só o excesso é relatado.** Um parâmetro faltante chega como `Nil` e muito
código conta com isso, então a falta é comum. Um a mais não pode ser alcançado
de forma alguma, então é sempre engano. Sob `--legacy` é um aviso.

## Tudo precisa ser declarado

Ler um nome não declarado é erro, não apenas atribuir a um.

> `Line 3: 'nNaoDeclarado' is not declared. Everything used in xtpl must be declared.`

Estes não são referências a variáveis e são deixados em paz: uma chamada
(`nome(`), um acesso a membro (`oUsuario:cNome`), um campo de banco
(`SA1->A1_COD`), um literal lógico (`.T.`, `.And.`), um `#define` no mesmo
arquivo, e qualquer nome que o transpilador tenha gerado.

### `external alias`

Para uma área de trabalho que quem chama abre. A mesma promessa que `external`
faz sobre um nome: ele existe, este arquivo apenas não enxerga de onde veio.

```xtpl
external alias SA1, SB1
```

Sem isso, uma referência de campo contra um alias que nada na função abriu é
relatada:

> `line 30: nothing in this function opened SD1. Wrap the use in 'using alias SD1 do', or declare 'external alias SD1' if the caller opens it.`

`using alias`, `rows`, `DbSelectArea` e `ChkFile` contam como abrir um.
Relatado uma vez por alias, e não uma vez por uso, e desligado sob `--legacy`,
onde um alias aberto por quem chama é a norma e não a exceção.

### `external`

Para nomes que existem mas que o transpilador não enxerga — uma constante de um
`#include` que ele não lê, ou uma `PUBLIC` definida por quem chamou:

```xtpl
#include "totvs.ch"

external STR0042, STR0043        // constantes do header de mensagens
external cEmpAnt, cFilAnt        // PUBLIC, definidas antes disto rodar
```

Em nível de arquivo, junto dos includes, porque é isso que esses nomes são: uma
constante de header é visível no arquivo inteiro e uma `PUBLIC` é visível em
todo lugar. Não emite nada — o código gerado fica igual.

**Legível, nunca atribuível.** `external` diz que o nome existe, não que ele é
seu para escrever:

> `Line 5: 'cEmpAnt' is external (line 1) and cannot be assigned.`

É uma promessa e não uma verificação, então um erro de digitação *dentro* da
declaração passa silenciosamente. Um `#define` no mesmo arquivo não precisa de
`external` — esses são encontrados automaticamente.

Um `#define` que chega por `#include` não é visível, nem uma `PUBLIC` definida
por quem chamou. Os dois são para isso que `external` serve. Um nome de campo
solto, usado sem o alias, continua sem resposta.

## Não verificado

Os dois atributos ficam na declaração, então não há nada a escrever no ponto de
chamada. Passar uma variável para uma função não precisa de marcador.
