# Changelog

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
