# examples

Programas inteiros, cada um com o `.xtpl` e o `.tlpp` que ele gera, para dar
para ver no que uma coisa vira sem precisar rodar nada.

| | |
|---|---|
| `pedido/` | `rows()` com `takewhile`: somar os itens de um pedido parando quando ele acaba, em vez de ler a tabela inteira |
| `consulta/` | `raw`: uma tela de comandos entregue ao pré-processador, e xtpl comum em volta dela. O único exemplo em que a versão à mão quase não perde |
| `notificacao/` | interpolação e os verbos de string: montar um texto e separar um que veio de fora |
| `romaneio/` | hashes: um cache de consultas que vai ao cadastro uma vez por produto, e a diferença entre a chave existir e o valor ter conteúdo |
| `apuracao/` | `defer`: conexão, tabela temporária e área abertas em sequência e desfeitas na ordem inversa, em cinco saídas diferentes |
| `modelo/` | `with object` sobre FWModel: o sujeito avaliado uma vez, blocos aninhados, e o `:` que não dá para escrever errado |
| `separacao/` | as estruturas de controle juntas: as três formas de `for`, `do case with`, `while local`, e as formas posfixadas `return/exit/loop if` |
| `parametros/` | `?:`: um valor que pode vir do parâmetro, da configuração do cliente, da geral ou de um padrão — e por que `Default` não serve |
| `etiqueta/` | `?.` e `?:`: um caminho de três níveis em que nenhum elo é garantido, e a diferença entre não existir e estar vazio |
| `fechamento/` | escopo de bloco e reaproveitamento de slot: seções que não veem umas às outras, e a variável capturada por um code block que não pode dividir armazenamento |
| `integra/` | `fallback`: três passos protegidos numa integração, e a diferença entre o que levanta erro e o que volta vazio |
| `creditos/` | `using alias` e `defer`: cinco saídas de uma função, e o ambiente restaurado em todas. Traz também `creditos_mao.tlpp`, a mesma função escrita à mão |
| `medias/` | limpar um arquivo texto e tirar a média de três campos por linha, numa passada, com a classe `Regex` do TLPP |
| `somar/` | somar campo a campo as linhas correspondentes de dois arquivos, com `zip` aninhado |
| `euler-1/` | o primeiro problema do Project Euler, sobre um intervalo |

Os `.tlpp` são **saída gerada** e estão versionados de propósito, para quem lê
o repositório. Isso só vale se forem regerados quando o transpilador muda:

```sh
for f in examples/*/*.xtpl; do python xtpl_transpiler.py "$f" "${f%.xtpl}.tlpp"; done
```

## O que cada um está tentando mostrar

Todo recurso aqui foi julgado por uma pergunta: **o que isto dá a quem
programa em AdvPL que o AdvPL puro já não dá?** Um exemplo que não consegue
responder isso é um recurso para reconsiderar, não um exemplo mal escrito.

`creditos` responde com clareza: a limpeza de três linhas aparece duas vezes
na versão à mão e teria de aparecer em toda saída nova. Esquecer uma não
quebra nada ali — quebra no laço de quem chamou, e parece outra coisa.

`pedido` responde de outro jeito: as duas versões têm quase o mesmo tamanho.
O ganho não é brevidade, é o que fica **dito**. Trocar `takewhile` por
`filter` — ou esquecer o `Exit` na versão à mão — continua dando a resposta
certa, só que lendo dois milhões de registros em vez de dez. Um erro que não
erra nada é o mais difícil de encontrar.

`integra` responde com a linha que se esquece: `ErrorBlock(bOld)`. O
ErrorBlock é da **thread**, não do bloco — trocar e não repor deixa o tratador
valendo para tudo que rodar depois, em qualquer função do sistema. São três
reposições na versão à mão, e esquecer uma basta. O estrago aparece no próximo
erro de outra pessoa.

`fechamento` responde de um jeito que nenhum dos outros responde: o ganho não
está no código gerado, está no que o transpilador **recusa**. Ler um
temporário da seção anterior compila e roda à mão, e dá o número errado. Em
xtpl o nome não existe fora do bloco.

`etiqueta` responde com a ordem dos testes. Escrito à mão,
`If oPedido:oEntrega != Nil .And. oPedido != Nil` lê o primeiro antes de
testar o segundo — o `.And.` avalia da esquerda para a direita, então a ordem
é o que protege, e invertê-la tira a proteção sem mudar a aparência. `?.`
gera a ordem certa por construção.

`parametros` responde com `Empty(0)`, que é `.T.` em AdvPL. Trocar
`If x == Nil` por `If Empty(x)` parece a mesma coisa e faz um desconto de zero
por cento — escolhido de propósito — virar o padrão de dez. `?:` testa `!= Nil`
e nada mais, então zero, `.F.` e `""` passam intactos.

`separacao` responde com a proporção: quantas linhas dizem o que a rotina
faz, e quantas dizem como o laço anda. Um `if/endif` de três linhas para um
único `Loop` está correto — mas na tela ele tem o mesmo tamanho de um bloco
que faz trabalho de verdade, e o olho não distingue.

`modelo` responde com o sujeito que não tem nome. Com dois objetos de nomes
parecidos em escopo, escrever `oMaster:SetValue` onde era `oContato:SetValue`
compila e grava no modelo errado. Dentro de um `with object` o sujeito é `:` —
não dá para escrever o outro por engano, porque não há outro para escrever.

`apuracao` responde com a saída que se acrescenta depois. O código à mão está
certo hoje: cinco saídas, cinco limpezas diferentes, cada uma desfazendo
exatamente o que já tinha sido feito até ali. Daqui a seis meses alguém põe um
`Return` num galho que parece simples e não leva as três linhas junto — a
tabela fica no banco, a função devolve o número certo, e o erro aparece na
execução seguinte, num `DbCreate` que não tem nada a ver.

`romaneio` responde com o temporário não limpo. `Get` deixa a variável
**intocada** quando a chave não existe, então uma leitura ausente traz o valor
da leitura anterior. O erro é intermitente: certo enquanto as chaves
existirem, e a primeira que faltar pega o peso do produto de antes. O xtpl
emite a limpeza antes de cada leitura, e são cinco no exemplo.

`notificacao` responde com o espaço. `"deve" + cValToChar(nValor)` sem o
espaço antes das aspas gruda duas palavras, e isso só aparece lendo a saída,
nunca o código. Na interpolação os espaços estão onde se vê que estão, porque
a frase está escrita como frase.

`consulta` responde admitindo um limite. As linhas `@ ... SAY ... GET` são
idênticas nas duas versões, e não há nada que o xtpl possa fazer por elas.
Numa rotina de tela, a tela costuma ser metade do arquivo — converter o resto
ganha menos do que ganharia numa rotina sem tela. Uma pasta de exemplos em que
tudo ganha muito é uma pasta que não ajuda a decidir nada.

Nem todo recurso responde tão bem. `?=` faz o mesmo que o `Default` que o
AdvPL já tem, e `docs/design.md` diz isso com todas as letras: é grafia. Vale
a pena saber quais são quais.
