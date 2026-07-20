# Cadastro de relacoes `orbit-relations-v1`

Esta versao e isolada das funcoes legadas do repositorio para nao alterar motores
existentes. A fonte executavel esta em
`apps/signals/orbit_engine/config/relations_v1.json`.

## Roda e atributos

A roda europeia usa o zero como indice 0:

`0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26`.

Cada numero possui indice fisico, dois vizinhos reais, paridade, cor, duzia,
coluna e setor (`VZ`, `TI` ou `OR`). O zero e neutro, verde, fora de duzia,
coluna, soma e familia terminal, mas participa normalmente da vizinhanca fisica.

As somas formam nove grupos de quatro:

- `SG1`: 1, 10, 19, 28
- `SG2`: 2, 11, 20, 29
- `SG3`: 3, 12, 21, 30
- `SG4`: 4, 13, 22, 31
- `SG5`: 5, 14, 23, 32
- `SG6`: 6, 15, 24, 33
- `SG7`: 7, 16, 25, 34
- `SG8`: 8, 17, 26, 35
- `SG9`: 9, 18, 27, 36

As familias terminais sao `147`, `258` e `369`, aplicadas ao ultimo digito.
Assim, 17 pertence a `147` na posicao 3 e 28 pertence a `258` na posicao 3.

## Espelhos

Os pares simetricos confirmados sao:

`1↔10, 2↔20, 3↔30, 6↔9, 12↔21, 13↔31, 16↔19, 23↔32, 26↔29`.

O par `14↔34`, encontrado em codigo legado, nao faz parte desta versao.

## Identificador orbital

O identificador e relativo ao pivo e muda a cada ocorrencia:

`IOR:orbit-relations-v1|P19|T-2|A1|N14|RF-15|DN-05|EQ[COR,DZ]|ES0|SG05S2|FT147P2`

- `P19`: pivo 19.
- `T-2`: segunda ocorrencia anterior do pivo.
- `A1`/`D1`: uma casa antes/depois do pivo.
- `N14`: numero observado.
- `RF` e `DN`: deslocamentos fisico e numerico assinados.
- `EQ`: atributos iguais ao pivo.
- `ES`: indicador de espelho.
- `SG...S...`: grupo e posicao da soma.
- `FT...P...`: familia e posicao terminal.

Qualquer alteracao semantica exige uma nova versao do cadastro para manter
replays e artefatos reproduziveis.
