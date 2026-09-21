# xtpl — por que é assim

Companheiro de [`language.md`](language.md), que diz **o que** a linguagem
faz. Este diz **por quê**, e o que ficou de fora.

Existe porque quase toda pergunta sobre uma linguagem é uma pergunta sobre
algo que foi considerado e recusado. Sem o registro, a mesma discussão volta.

---

## A regra que decidiu tudo

Cada recurso foi julgado por uma pergunta: **o que isto dá a quem programa em
AdvPL que o AdvPL puro já não dá?**

Aplicada honestamente, ela removeu mais do que acrescentou. As remoções
melhoraram a linguagem mais do que as adições.

Uma segunda regra apareceu depois e vale guardar: **análise vale a pena
construir, transformação quase nunca.** O que o transpilador consegue
*verificar* é valor distinto. O que ele apenas *reescreve* costuma estar ao
alcance de um `#xtranslate`, ou não vale a dependência.

---

## O que sobreviveu, e por quê

**Escopo de bloco com reaproveitamento de slot.** Um `local` dentro de um
bloco tem tempo de vida de pilha, e blocos irmãos dividem armazenamento. As
duas coisas são um recurso só: se cada `local` dentro de um `if` custasse um
slot permanente, uma função longa acabaria com quarenta declarações e as
pessoas aprenderiam a içar tudo à mão — abandonando a disciplina que o recurso
existe para impor. Foi isso que forçou a análise de escape que o `<contained>`
usa hoje.

**Só uma captura por code block impede o compartilhamento.** Passar uma
variável para uma função não é risco nenhum, faça a função o que fizer: o
AdvPL entrega o *objeto*, e reatribuir o nome depois não alcança aquilo. Um
code block é outra coisa — ele captura a *variável*. Vale para números e
strings exatamente como para arrays; não é sobre tipos.

**Fusão de cadeias.** Uma cadeia `|>` de etapas elemento a elemento vira um
laço só, sem array intermediário, e um `take` interrompe o percurso em vez de
cortar depois. Sobre `rows()` e `lines()` isso é a diferença entre ler uma
tabela inteira e parar no décimo registro.

**`using alias` e `defer`.** Restaurar área de trabalho e desfazer coisas em
toda saída, inclusive nos `return` antecipados. Esquecer de restaurar um alias
é um bug clássico de Protheus cujo estrago aparece em outro lugar
completamente.

**A verificação.** Campos, tipos e tamanhos contra o SX3; se o alias está
sequer aberto; contagem de argumentos; retornos que levam valor num caminho e
não noutro; nomes não declarados. Nada disso depende de ser um transpilador, e
nada disso o pré-processador alcança.

---

## O que foi recusado

Cada um destes foi considerado a sério, alguns construídos e depois removidos.
O motivo está resumido; o raciocínio completo está no registro interno.

| | |
|---|---|
| `let` | Duplicava `local` depois que `local` ganhou semântica de pilha |
| `gather` / `take` | A versão útil precisa de escopo dinâmico; a nossa era léxica, e então não era melhor que `aadd` |
| `given` / `when` | Uma cadeia `if`/`elseif` com vocabulário inventado. `Do Case` diz o mesmo em AdvPL que já se lê |
| `with` / `orwith` / `without` | Nunca ligavam o resultado do teste, então um ramo não podia usar o valor que acabara de achar |
| Operadores de dobra `[+]` `[max]` | Um operador para aprender onde uma função se lê sozinha, e não podiam ser etapa de cadeia |
| `?=>` | Encadeava sem os verbos e não fazia nada sem `fallback` |
| `for each` | As três formas de `for` se distinguem pelo formato, e `each` tomava emprestada a grafia do Harbour para algo mais restrito |
| `uniq` | Renomeado para `distinctAdjacent`: corre o risco de ser lido como `distinct`, e os dois dão respostas diferentes |
| Array de runtime em vez de slots gerados | `@aStk[1]` não é AdvPL válido, e capturar um slot capturaria o array inteiro |

**Direções inteiras recusadas**, cada uma depois de investigada:

- **Coroutines para concorrência.** O ganho de Erlang e do Loom vem do
  *runtime* ceder em I/O. Um transpilador só cede onde ele mesmo criou o
  ponto, e o primeiro `DbSeek` bloqueia a thread.
- **Geradores (`yield`).** Chegaram a ser desenhados por inteiro. O que vale
  iterar sob demanda no Protheus já é retomável — a workarea —, e onde a
  preguiça paga, na cadeia, a fusão resolve em tempo de compilação sem máquina
  de estados.
- **Um interpretador de xtpl.** Jogaria fora tudo que é tempo de compilação,
  que é onde está o valor.
- **HTTP/2 no AppServer.** Não é problema de linguagem; um proxy reverso é a
  arquitetura normal.
- **Açúcar para DynCall / FFI.** O TLPP já declara assinaturas estrangeiras;
  xtpl estaria repetindo conhecimento de plataforma num segundo lugar.
- **Junções.** Viraram `anyof` / `allof` / `noneof`, que dizem a mesma coisa
  sem operador novo.
- **Lambdas no estilo C++.** Inline perde legibilidade; a forma com estado não
  tinha caso de uso que alguém apresentasse.

---

## O que se aplicaria a um compilador de verdade

Escrito para quem lê isto como proposta de linguagem, e não como ferramenta.

**Não se aplicaria.** O reaproveitamento de slots é alocação de registradores,
que um compilador já faz invisivelmente. A fusão existe porque o AdvPL não tem
sequências preguiçosas; um compilador com representação intermediária ganha
isso de passes comuns. `rows()` e `lines()` existem porque não há protocolo de
iteração. `raw` existe porque o pré-processador roda depois. `--map` existe
porque a saída não se parece com a entrada.

**Se aplicaria, e é a proposta de verdade.** A verificação. Campos, tipos e
tamanhos; se o alias está aberto; contagem de argumentos; retornos
inconsistentes; escopo de bloco com análise de escape; `using alias`
restaurando em toda saída. Nada disso depende de ser um transpilador.

**O que uma estimativa precisa incluir**, e sobre o que construir isto não diz
nada: conviver com décadas de `.prw` e headers `#xtranslate`; o que qualquer
disso significa para o RPO, para o link, para patches de cliente; o depurador,
o TDS e a VM, que não são o compilador; e escrever semântica que hoje não está
escrita em lugar nenhum, acertando para todo chamador existente. Um compilador
de verdade tem uma tentativa por construção. Aqui `distinct` mudou de
significado duas vezes num dia.

---

## Medido contra o TypeScript

xtpl é forte onde o TypeScript era mais forte — **a verificação é o produto** —
e fraco nas duas coisas que de fato levaram o TypeScript à adoção:

- **não é um superconjunto.** Uma coisa impede um `.prw` existente de compilar:
  escrever num nome não declarado, que o AdvPL permite e transforma em
  `PRIVATE`. `--legacy` transforma isso em aviso.
- **a saída não se parece com a entrada.** `!aTmp^1^0!` não é o que a pessoa
  escreveu, ainda que leve o nome dela.

---

## Como isto foi verificado

Quatro camadas, em ordem do que cada uma consegue dizer:

**Testes de arquivo-referência.** Toda fixture tem sua saída esperada
gravada e comparada a cada execução. Dizem que o transpilador gera o que
gerava — e nada mais. Uma saída inválida gravada como esperada passa
indefinidamente, o que aconteceu.

**Fuzzing diferencial.** O transpilador tem dois caminhos de parsing, um por
gramática Raku e um por regex. `fuzz_paths.py` gera programas e compara os
dois. Acha divergências que nenhuma fixture cobre, e achou.

**O compilador do Protheus.** `compile_check.py` compila toda fixture e traduz
os erros de volta para a linha `.xtpl`. Dez faltas apareceram só aqui, quase
todas sobre a *forma* de uma declaração — o que nenhuma das camadas acima
consegue ver, porque comparam o transpilador consigo mesmo.

**Execução.** `54_selftest` faz 71 verificações de computação pura e
`55_envtest` faz 23 sobre área de trabalho, arquivo e pré-processador, cada
uma conferindo a resposta. Mais uma dúzia de faltas apareceu aqui — entre elas
um percurso sobre arquivo inexistente que **travava o servidor**, porque
`FT_FEof()` num arquivo que nunca abriu fica `.F.` para sempre.

Nenhuma das três primeiras camadas poderia ter encontrado a última.

---

## Contra código de verdade

121 arquivos `.prw` e `.tlpp` de seis repositórios públicos do GitHub, pelo
`--legacy`. **Todos os 121 passaram**, depois de sete correções que só eles
encontraram.

O que o modo legado relatou neles:

| | |
|---|---|
| 761 | nome não declarado |
| 164 | `PRIVATE` implícita — escrita num nome que nunca foi declarado |
| 105 | variável declarada e nunca usada |
| 46 | atribuída e nunca lida |
| 31 | função que retorna valor num caminho e cai no fim noutro |
| 24 | declaração fora do prólogo |
| 14 | redeclarada sobre um parâmetro |

Os nomes não declarados mais comuns são palavras de comando — `DEFINE`,
`MSDIALOG`, `ACTIVATE`, `PIXEL` — que é o sinal de que o arquivo é de tela e
quer `raw`, não conversão. Era exatamente para isso que a contagem existia.

As sete correções foram todas coisas que nenhuma fixture tinha: um `private`
com inicializador que não é constante (duas falhas de uma vez, nunca
exercitado), as três verificações novas disparando **dentro de comentários de
bloco** — um `<br>` numa documentação, prosa com parênteses —, um `local`
sobre um parâmetro de mesmo nome, que o Protheus aceita, e um **espaço não
separável** no lugar de um espaço comum, que algum editor deixou e que o
`\s` não casa.

## O que ainda não é verdade

Nada disto jamais rodou **em produção**, nem perto de dados de cliente. As
fixtures são sintéticas e foram escritas por quem escreveu o transpilador — o
que significa que uma verificação pode estar errada na mesma direção que o
código.

Os 121 arquivos acima foram lidos e verificados, não executados: `--legacy`
diz o que há neles, e a saída gerada nunca foi compilada nem rodada. Todo
arquivo de verdade que passou por aqui encontrou algo.
