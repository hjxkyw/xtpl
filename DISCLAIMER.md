# Isenção de responsabilidade

Este arquivo repete o que o README diz, para que possa ser encontrado por si
só e para que ninguém possa razoavelmente alegar que não foi avisado.

## Independência

xtpl é um projeto pessoal, independente e experimental. **Não tem qualquer
vínculo com a TOTVS S.A.** Não é endossado, revisado, patrocinado, apoiado nem
reconhecido pela TOTVS ou por qualquer pessoa ligada a ela. Nada aqui deve ser
lido como representando planos, posições ou opiniões da TOTVS.

TOTVS, Protheus, AdvPL, TL++ e demais nomes usados aqui são marcas de seus
respectivos titulares. Aparecem apenas para descrever o alvo deste projeto, em
uso nominativo. Nenhuma reivindicação é feita sobre elas.

## Fontes

Tudo aqui foi construído a partir de material **publicamente disponível**:
documentação publicada, artigos e exemplos publicados publicamente, e
experiência comum de uso da linguagem.

Nenhum código-fonte, especificação interna, roadmap, documentação não
divulgada ou outro material não público da TOTVS foi consultado, referenciado
ou reproduzido. Onde o comportamento de uma classe ou função da plataforma não
pôde ser confirmado pela documentação pública, esse fato está registrado em
`docs/decisions.md` como uma suposição a ser verificada, e não apresentado
como fato.

## Autoria

**Todo o código deste repositório foi gerado por uma IA**, em conversa com o
autor: o transpilador, o runtime, as gramáticas Raku, a suíte de testes, as
ferramentas e a documentação.

O autor definiu a direção, tomou as decisões de desenho, rejeitou parte
substancial do que foi proposto e é responsável pelo resultado. Mas a
implementação não foi escrita à mão, e deve ser lida com o ceticismo que isso
merece.

## Estado

- **Compila.** As 55 fixtures e o runtime passam pelo compilador do Protheus
  sem erros.
- **Roda.** `54_selftest` faz 71 verificações de computação pura e
  `55_envtest` faz 23 sobre área de trabalho, arquivo texto e o
  pré-processador. Todas passam.
- **Nada disso é código real.** As fixtures foram escritas por quem escreveu o
  transpilador, e nenhuma linha jamais rodou sobre uma base de código de
  verdade, em produção, ou perto de dados de cliente.
- Nunca foi usado sobre uma base de código real, nem perto de dados de
  cliente.
- A suíte de testes verifica que o transpilador gerou o que gerou. Ela não
  consegue verificar que o resultado faz o que o fonte diz. Um erro dessa
  forma foi encontrado tarde: saída inválida gravada como esperada, que passou
  enquanto ninguém olhou.

**Compilar não é funcionar. Assuma que o código gerado está errado até que
você mesmo o tenha executado e conferido.**

## Adequação

Esta é uma ferramenta para **pensar sobre desenho de linguagem**, não para
escrever software do qual você dependa. É oferecida na esperança de que o
registro de decisões seja útil a quem estiver considerando as mesmas
perguntas.

Não a use para gerar código de sistema em produção. Não a use perto de dados
de cliente. Não trate sua saída como revisada.

## Responsabilidade

Fornecido **como está, sem garantia de qualquer natureza**, expressa ou
implícita, incluindo, sem limitação, as garantias de comercialização,
adequação a uma finalidade específica e não violação de direitos.

O autor não será responsável por qualquer reivindicação, dano ou outra
responsabilidade, seja em ação contratual, extracontratual ou de outra
natureza, decorrente de, ou relacionada a, este software ou seu uso —
incluindo, sem limitação, código que não compile, código que compile e se
comporte incorretamente, dados corrompidos ou perdidos, indisponibilidade ou
tempo despendido.

O uso deste software é inteiramente por sua conta e risco. Se você implantar
sua saída em algum lugar que importe, essa decisão e suas consequências são
suas.

---

*An English version of this notice is kept in `DISCLAIMER.en.md`.*
