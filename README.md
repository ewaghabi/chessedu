# ChessEdu (Local)

Aplicativo local para estudar suas partidas do Chess.com com foco em abertura, padrões recorrentes e treino de tática a partir dos seus próprios erros.

## Principais funcionalidades

- Sincronização incremental de partidas via API pública do Chess.com.
- Armazenamento local em SQLite (`games.db`) e indexação de posições por lance.
- Exploração de posição atual com:
  - próximos lances mais jogados;
  - taxa de vitória por lance (do ponto de vista do usuário);
  - lista de partidas que passaram pela posição.
- Filtros avançados por:
  - cor jogada (`any`, `white`, `black`);
  - ritmos (`blitz`, `rapid`, `bullet`, `outros`);
  - opção de ignorar derrotas por tempo.
- Contadores no painel de filtros:
  - `Partidas` (com filtros aplicados);
  - `Problemas` (quantidade de problemas táticos disponíveis para os mesmos filtros).

## Treino de problemas (novo)

- Botão **GO!** ao lado de `Problemas` abre um modal de treino.
- Cada problema é uma posição extraída previamente pelo batch com Stockfish.
- Fluxo do modal:
  - sorteio aleatório sem repetição até consumir a lista filtrada;
  - tabuleiro orientado para o lado a jogar;
  - exibição de jogadores e ELO;
  - cronômetro por problema;
  - validação imediata do lance com feedback visual;
  - ações: **Próximo problema**, **Repetir**, **Pular problema**.
- UX de movimento refinada:
  - arrastar/soltar com melhor sincronização visual;
  - cursor com a imagem da peça durante o drag (com fallback).

## Batch de geração de problemas

O projeto inclui um processo dedicado (`problems.py`) para identificar posições-problema a partir das partidas já sincronizadas.

Exemplo:

```bash
.venv/bin/python problems.py --max-games 100 --eval-time 1.0 --eval-delta 3.0
```

Esse processo:

- analisa partidas com Stockfish;
- detecta swings de avaliação acima do limiar;
- popula a tabela `problem_positions`;
- suporta execução incremental por combinação de parâmetros.

## Como rodar

```bash
cd /Users/eduardowaghabi/chessedu
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Acesse [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Testes

```bash
python -m unittest discover -s tests -v
```

## Fluxo recomendado

1. Sincronize partidas com **Atualizar banco (incremental)**.
2. Navegue no tabuleiro principal para estudar lances e resultados.
3. Gere/atualize problemas com `problems.py` quando quiser ampliar o banco tático.
4. Use o botão **GO!** para treinar os problemas no modal.

## Observações

- O histórico detalhado de mudanças está em `changelog.md`.
- Nesta etapa, o treino no modal ainda não persiste métricas de acerto/tempo no banco; isso pode ser habilitado em uma evolução futura.
