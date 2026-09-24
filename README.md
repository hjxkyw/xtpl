# xtpl

> **Projeto arquivado.** O xtpl está descontinuado e hoje só serve de apoio
> para o nascimento do [xc](https://github.com/hjxkyw/xc), que o substitui: o
> mesmo dialeto, lido por uma gramática de verdade em vez de expressões
> regulares. Os testes, os erros e o runtime daqui são a base do xc. O código
> fica aqui para consulta.

*English version: [README.en.md](README.en.md).*

Um compilador experimental de código para código: recebe um dialeto de mais
alto nível de AdvPL/TL++ e gera TL++ comum, que compila e roda no Protheus.

```xtpl
using alias SC6 order 1 do
  nTotal := rows("SC6", xFilial("SC6") + cNum) ;
            |> takewhile([r] r:C6_NUM == cNum)  ;
            |> map([r] r:C6_VALOR)              ;
            |> asum
end using
```

Uma passada só na tabela, sem array intermediário, parando quando o número do
pedido muda — e a área de trabalho devolvida como estava, inclusive se houver
um `return` no meio.

Criado para responder a uma pergunta: **quais recursos de linguagem modernos
poderiam ser oferecidos a quem programa em Protheus sem mudar o runtime?**
O argumento do TypeScript, aplicado ao AdvPL.

> **Sem qualquer vínculo com a TOTVS.** Projeto pessoal, experimental, escrito
> por uma IA, nunca usado em produção. Leia
> [DISCLAIMER.md](DISCLAIMER.md) antes de qualquer coisa — é curto e importa.

---

## O que ele faz

| | |
|---|---|
| **Verificação** | campos, tipos e tamanhos contra um SX3 exportado; alias que ninguém abriu; contagem de argumentos; retorno que existe num caminho e não noutro; nomes não declarados; variáveis sem uso |
| **Escopo** | `local` com tempo de vida de bloco, reaproveitamento de slot e análise de escape |
| **Pipelines** | cadeias `\|>` que viram um laço só, sobre arrays, áreas de trabalho e arquivos texto |
| **Áreas de trabalho** | `using alias SA1 order 1 do ... end using`, restaurada em toda saída |
| **Sintaxe** | `?:`, `?.`, `?=`, interpolação, hashes, `if`/`while` posfixados, `defer`, `fallback` |
| **Código existente** | `--legacy` lê um `.prw` como ele é, avisando em vez de recusar |

A referência completa está em [`docs/language.md`](docs/language.md).

## Situação atual

- **Compila.** As 55 fixtures e o runtime passam pelo compilador do Protheus
  sem erros.
- **Roda.** Duas fixtures se executam no ambiente conferindo cada resposta:
  71 verificações de computação pura e 23 sobre área de trabalho, arquivo
  texto e pré-processador. Todas passam.
- **Lê código de verdade.** 121 arquivos `.prw` e `.tlpp` de seis
  repositórios públicos passam por `--legacy`.
- **Nunca rodou em produção**, com dados reais, e nenhum código gerado chegou
  a ser implantado.

## Experimentando

```sh
python run_tests.py                   # 83 fixtures, nos dois caminhos de parsing
python xtpl_transpiler.py meu.xtpl    # gera meu.tlpp ao lado
python xtpl_transpiler.py --legacy antigo.prw    # o que há num arquivo existente
```

Python 3.10 ou superior, sem dependências obrigatórias.

Opcionalmente, [`rakulang`](https://github.com/ash/rakupp) habilita o caminho
por gramática Raku para quatro construções. Sem ele usa-se o fallback por
regex, e os dois são obrigados a produzir saída idêntica — `run_tests.py` diz
qual caminho usou, porque a contagem sozinha não distingue.

Ele **não está no PyPI**: as wheels são anexos de release no GitHub, e a
wheel já traz a `librakupp.so` dentro. Para Linux x86-64:

```sh
curl -sfL -O https://github.com/ash/rakupp/releases/download/v4.0.1/rakulang-0.1.0-py3-none-linux_x86_64.whl
pip install rakulang-0.1.0-py3-none-linux_x86_64.whl
```

O nome do arquivo importa: o pip recusa a wheel se ela for renomeada. Para
outra plataforma, a lista de anexos está em
`https://github.com/ash/rakupp/releases` — há `linux_aarch64` e
`macosx_arm64`. Compilar a partir do fonte não é necessário.

`fuzz_paths.py` precisa dos dois caminhos e se recusa a rodar sem o rakulang.

**Antes de compilar qualquer coisa**, compile `xtpl_runtime.tlpp` num RPO
customizado: ele define as funções `u_xtpl_*` e a classe `XtplQueue`, e nada
do que for gerado linka sem isso.

### Usando o compilador AdvPL/TL++

```sh
python compile_check.py ^
  --compiler "appserver.exe -compile -files={file} -includes=C:\inc -env=MeuAmbiente"
```

Transpila toda fixture com `--map`, compila cada uma, e traduz qualquer erro de
volta para a linha `.xtpl` que o produziu. `{file}` é o único marcador.

### Executando os testes

```sh
appserver.exe -env=MeuAmbiente -run=u_selftest    # 71 verificações
appserver.exe -env=MeuAmbiente -run=u_envtest     # 23, com tabela e arquivo proprios
```

## Repositório

```
xtpl_transpiler.py    o transpilador
xtpl_grammar.raku     quatro gramáticas Raku, usadas quando o rakulang existe
xtpl_runtime.tlpp     funções de apoio; compile num RPO customizado
run_tests.py          testes de arquivo-referência
compile_check.py      passar a saída por um compilador de verdade
fuzz_paths.py         fuzzing diferencial dos dois caminhos de parsing
tests/                55 fixtures, cada uma com saída e avisos esperados
errors/               28 casos que devem ser recusados, com suas mensagens
docs/language.md      a referência da linguagem
docs/design.md        por que é assim, e o que foi rejeitado
```

Comentários de código estão em inglês; a documentação, em português.

## Contribuindo

Relatos de erro são bem-vindos, sobretudo qualquer coisa que não compile ou
que dê resposta errada.

## Licença e ressalvas

[MIT](LICENSE). Sem garantia, e o autor não se responsabiliza por nada que
decorra do uso.

Tudo isto foi gerado por uma IA em conversa com o autor, que conduziu o
desenho e rejeitou boa parte do que foi proposto, mas não escreveu a
implementação à mão. Nada aqui usou informação interna da TOTVS. TOTVS,
Protheus, AdvPL e TL++ são marcas de seus titulares.

Os detalhes estão em [DISCLAIMER.md](DISCLAIMER.md), e valem a leitura.
