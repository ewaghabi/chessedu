# Chess.com Opening Explorer (Local)

Visualizador local para estudar suas aberturas com base nas suas partidas do Chess.com.

Versão atual: `0.1` (ver `changelog.md`).

## O que faz

- Sincroniza partidas diretamente da API pública do Chess.com.
- Salva em SQLite (`games.db`) local.
- Atualização incremental por arquivo mensal (archives).
- Indexa posições e próximos lances para consulta rápida.
- Mostra, para a posição atual:
  - próximos lances jogados,
  - quantidade de partidas,
  - taxa de vitória (%), do seu ponto de vista.
- Lista as partidas que passaram pela posição e permite carregar uma partida no tabuleiro.

## Rodar

```bash
cd /Users/eduardowaghabi/chessedu
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abra [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Testes

```bash
python -m unittest discover -s tests -v
```

## Fluxo de uso

1. Informe seu username do Chess.com.
2. Clique em **Atualizar banco (incremental)**.
3. Explore os lances sugeridos clicando em **Entrar**.
4. Em qualquer posição, clique em **Ver partidas desta posição** para abrir a lista.
5. Clique em **Carregar** numa partida para ver o jogo no tabuleiro.

## Observações

- A sincronização incremental considera novos arquivos mensais ainda não sincronizados.
- Se o Chess.com alterar partidas em um mês já sincronizado, clique em "reset" do banco (não implementado ainda) ou remova `games.db` para forçar carga completa.
