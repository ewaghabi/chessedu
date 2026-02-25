# Changelog

## 0.10.0
- Modal de problemas ganhou ação de exclusão individual com botão de lixeira no canto inferior direito.
- Exclusão protegida por modal de confirmação customizado (sem `alert`), com opções de cancelar ou confirmar.
- Novo endpoint backend `DELETE /api/problems/<problem_id>` para remoção segura de problemas, com tratamento de erro para item inexistente/tabela ausente.
- Fluxo da sessão atualizado após exclusão: remove o problema da fila atual, atualiza contagens e avança automaticamente para o próximo (ou encerra a sessão se não houver mais problemas).
- Cobertura de testes ampliada para o endpoint de exclusão e para os novos artefatos/frontend do modal de confirmação.

## 0.9.0
- Pipeline de geração de problemas unificado para usar os mesmos critérios da análise em tabela (`c1..c5`) como regra oficial de seleção.
- Novo modo de debug direcionado por jogo: adicionado parâmetro `--game-id` no `problems.py` para processar somente uma partida específica.
- Reprocessamento forçado por jogo/parâmetros ao usar `--game-id`, limpando apenas os registros correspondentes em `problem_positions` e `problem_scan_runs`.
- Saída da tabela aprimorada para auditoria:
  - nova coluna `jogado` com SAN numerado (`1.e4`, `1...Nc6`);
  - coluna `pv1` convertida para SAN numerado (em vez de UCI), mantendo truncamento para leitura.
- Fluxo de progresso mantido por lance (`Analisando ...`) e consolidado com linha final de conclusão por jogo.
- Cobertura de testes ampliada para o novo filtro por `game_id`, reprocessamento forçado e novas colunas SAN da tabela.

## 0.8.0
- Gerador de problemas refinado para focar apenas em chances desperdiçadas: além do filtro de swing e relevância competitiva, posições em que o lance jogado coincide com a PV principal são descartadas.
- Persistência de PV ampliada: problemas agora armazenam linha completa em UCI (`pv_line_uci`) e SAN (`pv_line_san`), mantendo `pv_move_uci` para compatibilidade.
- Nova avaliação final baseada na solução: adicionado `eval_pv_final`, calculado após aplicar a PV completa na posição, com exibição no modal.
- Correção de bug crítico em cenários de mate: valores de mate não colapsam mais para `+0` no cálculo de avaliação.
- Modal de problemas atualizado:
  - enunciado dinâmico com objetivos de treino (`obtêm vantagem decisiva`, `revertem a partida`, `igualam a posição`);
  - feedback simplificado (`Correto.` / `Incorreto.` sem eco do lance jogado);
  - botão `Mostrar solução` exibido somente após erro e ocultado após revelar PV+eval, mantendo fluxo de avanço para próximo problema.
- Endpoint `GET /api/problems` estendido para expor `pv_line_uci`, `pv_line_san` e `eval_pv_final`.
- Cobertura de testes ampliada para novos campos, regras de seleção de problemas, conversão SAN, avaliação após PV e regressões de mate.

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
