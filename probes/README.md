# probes

Arquivos `.tlpp` escritos para perguntar uma coisa ao Protheus e ver a
resposta. Cada um imprime o que encontrou e, quando dá, confere o próprio
resultado.

Quase tudo que o xtpl sabe sobre AdvPL/TL++ que não estava na documentação
veio daqui:

| | |
|---|---|
| `probe_assign` | `:=` é uma expressão e devolve o valor atribuído — em `If`, em `While`, encadeado, como argumento |
| `probe_ftuse` | uma abertura `FT_FUse` que falha **não** é inerte: desloca o arquivo corrente, e o `FT_FUse()` seguinte fecha o de outro |
| `probe_regex` | a classe `Regex` do TLPP; `matches` é estático e exige a string inteira — e o exemplo do TDN está errado |
| `probe_hash`, `probe_hash2`, `probe_hash3` | `THashMap`: `Get(k, @x)`, `List(@a)` enche `{{chave, valor}, ...}`, `Del`, `Count` |
| `probe_db` | criar, abrir, popular, ler e apagar uma tabela: `TCLink`, `DbCreate(..., "TOPCONN")`, `DbAppend(.F.)`, `TCDelFile` |
| `probe_translate`, `probe_shared_slot`, `probe_generic`, `probe_blk` | o que o pré-processador aceita num `#translate`, e se um alias quebra a captura de um code block |
| `probe_control` | gerado de `probe_control.xtpl`: estruturas de controle sobre slots compartilhados |

Rodar:

```sh
appserver.exe -compile -files=probes/probe_assign.tlpp -includes=... -env=SeuAmbiente
appserver.exe -env=SeuAmbiente -run=u_probeAssign
```

**Os probes escritos à mão não são atualizados quando o xtpl muda.** Vários
usam `__stk_`/`__blk_`, que era como os nomes gerados se chamavam quando eles
foram escritos. Reescrevê-los faria dizerem que testaram algo que não
testaram — são o registro do que foi realmente executado, não exemplos do
estado atual. Só `probe_control.tlpp` é gerado, e esse acompanha.
