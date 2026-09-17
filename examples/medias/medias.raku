#!/usr/bin/env raku

# medias.raku -- limpar um arquivo e tirar a media de cada linha, numa passada.
#
# Cada linha deve ter tres campos numericos separados por virgula. As que tem,
# viram a media dos tres; as que nao tem sao descartadas e contadas.
#
# A primeira versao fazia
#
#     my @linhas = $arquivo.lines;
#     my @medias = @linhas.map(...).grep(...).map(...);
#
# e isso le o arquivo inteiro para a memoria: atribuir uma Seq preguicosa a um
# array com sigilo @ a reifica. Depois o pipeline percorre esse array de novo.
#
# Encadeando direto em $arquivo.lines a preguica se mantem do comeco ao fim --
# map e grep sobre uma Seq sao preguicosos, e a atribuicao final a @medias e
# o que puxa tudo. Uma passada, uma linha na memoria por vez.
#
# A contagem anda junto, dentro do primeiro map, pela mesma razao: contar antes
# com um $arquivo.lines.elems separado leria o arquivo duas vezes.

sub medias(IO::Path $arquivo) {
    my $lidas = 0;

    my @medias = $arquivo.lines
        .map({ $lidas++; .split(',')».trim })
        .grep({ .elems == 3 && all(.list) ~~ / ^ '-'? \d+ [ '.' \d+ ]? $ / })
        .map({ .sum / 3 });

    note "linhas: $lidas  boas: {@medias.elems}  " ~
         "descartadas: {$lidas - @medias.elems}";

    return @medias;
}

sub MAIN(IO::Path $arquivo where *.f) {
    .say for medias($arquivo);
}
