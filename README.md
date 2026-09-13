# xtpl

*English version: [README.en.md](README.en.md).*

Um compilador experimental de código para código, que recebe um dialeto de
mais alto nível de AdvPL/TL++ e gera TL++ comum.

Existe para responder a uma pergunta: **quais recursos de linguagem modernos
poderiam ser oferecidos a quem programa em Protheus sem alterar o runtime?**
O argumento do TypeScript, aplicado ao AdvPL.

---

## Leia isto antes de qualquer coisa

**Sem qualquer vínculo com a TOTVS.** Este é um projeto pessoal e
independente. Não é endossado, revisado, patrocinado nem apoiado pela TOTVS
S.A. ou por qualquer pessoa ligada a ela. TOTVS, Protheus, AdvPL e TL++ são
marcas de seus respectivos titulares e aparecem aqui apenas para descrever o
que este projeto tem como alvo.

**Nenhuma informação interna ou confidencial foi utilizada.** Tudo aqui foi
construído a partir de documentação pública, artigos publicados publicamente e
experiência comum de uso da linguagem. Nenhum código-fonte, especificação,
roadmap ou outro material não público da TOTVS foi consultado.

**Todo o código foi escrito por uma IA.** O transpilador, o runtime, as
gramáticas, a suíte de testes e a documentação foram gerados por um modelo de
linguagem em conversa com o autor. O autor conduziu o desenho, tomou as
decisões e rejeitou boa parte do que foi proposto — mas não escreveu a
implementação à mão. Leia o código com isso em mente.

**Compila e roda.** As 55 fixtures e o runtime passam pelo compilador do
Protheus limpos, e duas delas se executam no ambiente conferindo cada
resposta: `54_selftest` faz 71 verificações de computação pura — funções do
runtime, a aritmética de uma cadeia fundida, operadores, hash, fila, ordem dos
`defer`, escopo de bloco — e `55_envtest` faz 23 sobre o que precisa de
ambiente, criando a própria tabela e o próprio arquivo texto para exercitar
`rows()`, `lines()`, `using alias` e `raw`. Todas passam.

Isso foi conquistado a duras penas: dez erros distintos só apareceram quando
um compilador de verdade os viu, e mais uma dúzia quando o código enfim rodou
— entre eles um laço sobre um arquivo inexistente que **travava o servidor**,
coisa que nenhum teste deste lado poderia ter encontrado.

**O que ainda nunca aconteceu:** nada aqui jamais tocou uma base de código
real, um sistema em produção, nem dados de cliente. As fixtures são
sintéticas, escritas por quem escreveu o transpilador.

**Nunca rodou em produção, nem perto disso.** Nenhum cliente, nenhum ambiente,
nenhum dado. Não coloque perto de nenhum dos três.

**Sem garantia, sem responsabilidade.** Fornecido como está. O autor não se
responsabiliza por nada que decorra do uso — incluindo, sem limitação, código
que não compila, código que compila e faz a coisa errada, perda de dados ou
tempo desperdiçado. Veja LICENSE e
[DISCLAIMER.md](DISCLAIMER.md).

**Experimental, e provavelmente continuará assim.** Construções foram
renomeadas, tiveram sua semântica alterada e foram removidas repetidamente
durante o desenvolvimento. Nada aqui é estável. Não há política de versão, não
há política de descontinuação e não há suporte.

---

## Para que isto serve de verdade

Sinceramente: **para prototipar desenho de linguagem**, mais do que para
escrever código.

O artefato mais útil deste repositório provavelmente é
[`docs/design.md`](docs/design.md) — por que a linguagem é assim, e o que foi
recusado. Contém mais coisas descartadas do que mantidas, e esse é o ponto.

Algumas das descobertas, nenhuma delas óbvia antes de tentar construir:

- `for each` não pode tomar emprestada honestamente a grafia do Harbour,
  porque um transpilador precisa escolher uma tradução em tempo de compilação
  e a do Harbour decide em tempo de execução.
- Um registro de área de trabalho não é um valor, então
  `for each oRow in rows("SA1")` é incoerente, por mais natural que pareça.
- `distinct` e `distinctAdjacent` são algoritmos genuinamente diferentes, e
  uma linguagem que queira os dois precisa dos dois nomes.
- Uma guarda que dobra comandos dentro de um code block não consegue conter um
  laço.

Se você está pensando no que o AdvPL poderia se tornar, esse registro talvez
poupe seu tempo. Se você quer uma ferramenta para escrever código Protheus
hoje, provavelmente não é isto.

## O que ele faz

Em linhas gerais, sobre o AdvPL:

| | |
|---|---|
| **Análise** | verificação de campos, tipos e tamanhos contra um SX3 exportado; nomes não declarados; aliases não abertos; contagem de argumentos; retornos inconsistentes; variáveis sem uso |
| **Escopo** | `local` com escopo de bloco e tempo de vida de pilha, reaproveitamento de slots e análise de escape |
| **Pipelines** | cadeias `\|>` que se fundem em um único laço, sobre arrays, áreas de trabalho e arquivos texto |
| **Áreas de trabalho** | `using alias SA1 order 1 do ... end using`, restaurada em toda saída, inclusive `return` antecipado |
| **Açúcar** | `?:`, `?.`, `?=`, interpolação de strings, literais e índices de hash, `if`/`while` posfixados, `defer`, `fallback` |
| **Adoção** | `--legacy` transforma em aviso a única coisa que impede o dialeto de aceitar um `.prw` existente: escrever em nome não declarado |

Veja [`docs/language.md`](docs/language.md) para a referência.

## Experimentando

```sh
python3 run_tests.py                     # 74 fixtures, nos dois caminhos de parsing
python3 xtpl_transpiler.py meu.xtpl       # gera meu.tlpp ao lado
python3 xtpl_transpiler.py meu.xtpl outro.tlpp
```

Python 3.10 ou superior. Sem dependências obrigatórias.

Opcionalmente, [`rakulang`](https://github.com/ash/rakupp) — um wheel
distribuído nos releases daquele projeto, não no PyPI — habilita o caminho por
gramática Raku para quatro construções. Sem ele usa-se o fallback por regex, e
os dois são obrigados a produzir saída idêntica.

**Antes de gerar qualquer coisa que você pretenda compilar**, compile
`xtpl_runtime.tlpp` em um RPO customizado. Ele define todas as funções
`__xtpl_*` e a classe `XtplQueue`, e nada do que for gerado vai linkar sem
isso.

### Verificando contra um compilador de verdade

```sh
python compile_check.py ^
  --compiler "appserver.exe -compile -files={file} -includes=C:\inc -env=MeuAmbiente"
```

Transpila todas as fixtures com `--map`, compila cada uma e traduz qualquer
erro de volta para a linha `.xtpl` que o produziu. `{file}` é o único
marcador — o resto do comando passa como você digitou.

### Rodando

Compilar não é funcionar. Depois que os arquivos estão no RPO, o AppServer
chama uma função direto:

```sh
appserver.exe -env=SeuAmbiente -run=u_selftest
```

`54_selftest` é a fixture feita para isso: ela confere as próprias respostas e
imprime um total.

```
selftest: 63 ok, 0 falhas
```

### Verificando se os dois caminhos de parsing concordam

```sh
python3 fuzz_paths.py --runs 400
```

Gera programas e compara o caminho por gramática com o caminho por regex. Dois
erros saíram da primeira execução.

### Versão

`VERSION.TXT` tem o número, e `python xtpl_transpiler.py --version` o mostra.
`MANIFEST.TXT` lista as fixtures da release; `run_tests.py` e
`compile_check.py` avisam sobre arquivos que sobraram de uma release anterior,
que é o que acontece ao descompactar por cima.

## Repositório

```
xtpl_transpiler.py    o transpilador
xtpl_grammar.raku     quatro gramáticas Raku, usadas quando o rakulang existe
xtpl_runtime.tlpp     funções de apoio; compile em um RPO customizado
run_tests.py          testes de arquivo-referência
compile_check.py      passar a saída por um compilador de verdade
fuzz_paths.py         fuzzing diferencial dos dois caminhos de parsing
tests/                fixtures, cada uma com sua saída e seus avisos esperados
errors/               casos que devem ser recusados, com suas mensagens
docs/language.md      a referência da linguagem
docs/design.md        por que é como é, e o que foi rejeitado
```

Os documentos que importam para ler e decidir estão em português. Comentários
de código continuam em inglês, como é usual.

## Contribuindo

Relatos de erro são bem-vindos, especialmente qualquer coisa que não compile —
essa é a lacuna que a suíte de testes não consegue fechar.

Pedidos de recurso são mais difíceis. Cada construção aqui foi julgada por uma
pergunta: **o que isto dá a quem programa em AdvPL que o AdvPL puro já não
dá?** Aplicada honestamente, ela removeu mais do que acrescentou.
`docs/design.md` registra o que já foi considerado e rejeitado, e por quê;
por favor leia a entrada correspondente antes de propor algo que ela já cobre.

## Licença

Veja [LICENSE](LICENSE) — MIT.
