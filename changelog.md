# Changelog

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
