# Changelog

## 0.7.0
- Novo modo de treino de problemas com botão `GO!` no painel de filtros e modal dedicado para resolução tática.
- Novo endpoint `GET /api/problems` com suporte aos mesmos filtros do app (`color`, `time_classes`, `ignore_timeout_losses`) e retorno de posição, lance esperado (PV), metadados da partida e ELO dos jogadores.
- Fluxo de treino implementado no frontend com:
  - sorteio aleatório sem repetição até consumir a lista filtrada;
  - tabuleiro orientado pelo lado a jogar;
  - cronômetro por problema;
  - validação imediata de lance (UCI exata), com ações `Próximo problema`, `Repetir` e `Pular problema`.
- Melhorias de UX no tabuleiro do modal:
  - renderização robusta ao abrir/redimensionar modal;
  - interação de arrastar/soltar refinada;
  - cursor com imagem da peça durante o movimento (fallback para `grabbing`).
- Cobertura de testes ampliada para contrato do endpoint `/api/problems`, filtros de problemas, artefatos do modal e regressões da lógica de treino no frontend.

## 0.6.0
- Novo batch dedicado em `problems.py` para extração incremental de posições-problema com Stockfish, com parâmetros de tempo por lance e delta mínimo de avaliação.
- Persistência de problemas em novas estruturas SQLite (`problem_positions` e `problem_scan_runs`) e marcação de processamento em `games.tactics_last_processed_at`, com migração aditiva preservando dados existentes.
- UX do batch melhorada com progresso contínuo em linha durante cada jogo e interrupção graciosa por `Ctrl+C` sem traceback.
- Painel de filtros da UI atualizado para exibir duas métricas: `Partidas` e `Problemas` (quantidade de problemas nos jogos filtrados), com extensão do endpoint `/api/count` para retornar `problems_count`.
- Cobertura de testes ampliada para batch, incremental por parâmetros, tratamento de interrupção, migração de schema e nova contagem de problemas por filtro.

## 0.5.0
- Filtros avançados no painel: ritmo com opção `outros`, opção para ignorar partidas com timeout, e contador total de partidas conforme filtros aplicados.
- Robustez de carregamento de estado: quando há partidas no banco e o usuário salvo está ausente, o backend infere e preenche automaticamente o usuário mais frequente.
- Correção de regressão no frontend por erro de sintaxe em `app.js`, agora coberta por teste dedicado de validação de sintaxe JavaScript.
- Refinamentos visuais: numeração de lances (`n.` / `n...`), sombreado por percentual de vitórias na lista de lances, destaque de partidas por resultado (vitória/derrota/empate) e botões `|<`/`<` no painel de lances.

## 0.4.0
- Frontend remodelado para layout em 3 painéis verticais (settings/filter, tabuleiro/partidas, lista de lances), ocupando quase toda a viewport.
- Branding atualizado para `ChessEdu` com versão no cabeçalho e remoção do subtítulo.
- Painel central ajustado com tabuleiro reduzido e centralizado, controles de replay centralizados e lista de partidas movida para baixo do tabuleiro.

## 0.3.0
- Interface de análise ajustada com filtros/controles de navegação e carregamento de partidas por clique.
- Metadados da partida aprimorados com nomes, ratings, data, ritmo e resultado formatado como placar (`1-0`, `0-1`, `1/2-1/2`) com motivo.
- API de partidas estendida para retornar `result_label` também em `/api/games`, com cobertura de teste de regressão.

## 0.2.0
- Fluxo de sincronização com UX melhorada: botão com spinner, estado desabilitado e mensagem contextual de sucesso/erro.
- Tabuleiro migrado para bibliotecas vendorizadas locais (`jquery`, `chess.js`, `chessboard.js` e peças PNG), removendo dependência de CDN.
- Robustez de frontend ampliada com captura global de erros e inicialização defensiva.
- Suíte de testes ampliada com regressões para carregamento de bibliotecas e contrato de artefatos frontend.

## 0.1
- Versão inicial.
