# AGENTS.md

## Objetivo do projeto
Este repositório contém um aplicativo local para analisar partidas do Chess.com com foco em estudo de aberturas e identificação de erros recorrentes.

## Stack técnica
- Backend: Python 3 + Flask
- Banco local: SQLite
- Parser de xadrez/PGN: `python-chess`
- Frontend: HTML/CSS/JavaScript (vanilla)
- Testes: `unittest` (stdlib)

## Estrutura do codebase
- `app.py`: servidor Flask, sincronização com API do Chess.com, persistência SQLite e endpoints REST.
- `templates/index.html`: interface web local.
- `static/app.js`: lógica de UI (tabuleiro, navegação de lances, chamadas API).
- `static/style.css`: estilos da interface.
- `tests/`: suíte de testes unitários e de integração.
- `requirements.txt`: dependências de execução e testes.

## Regras de engenharia
- Aplicar DRY (Don't Repeat Yourself): evitar duplicação de lógica e constantes.
- Aplicar SoC (Separation of Concerns):
  - backend: dados/sincronização/API;
  - frontend: renderização/interação;
  - testes: comportamento e regressão.
- Preferir funções pequenas, com responsabilidade única.
- Escrever nomes explícitos para funções, variáveis e testes.
- Tratar erros com mensagens acionáveis para usuário e para debug.
- Evitar acoplamento entre camadas (UI não deve depender de SQL direto, por exemplo).

## Primitivas obrigatórias de execução
- Nunca implementar código diretamente após um pedido de mudança: primeiro submeter um plano de implementação para revisão e aprovação do usuário.
- Toda vez que um erro de comportamento/técnica/prática de desenvolvimento for confirmado, registrar o erro neste `AGENTS.md` com causa raiz e ação preventiva para evitar repetição.
- Sempre que o usuário escrever "gravar uma minor", executar obrigatoriamente:
  1) suíte completa de testes;
  2) incremento de versão em `major.minor.patch` (incrementar `minor`, zerando `patch`);
  3) nova entrada no `changelog.md` com principais modificações;
  4) commit local;
  5) confirmação explícita da branch antes de qualquer push remoto.

## Registro de erros confirmados
- 2026-02-25 - PV de problemas era persistida apenas com o primeiro lance UCI, causando exibição incompleta e sem notação SAN no modal.
  - Causa raiz: pipeline de análise descartava a linha completa retornada em `info["pv"]` e armazenava apenas `pv[0]`.
  - Prevenção: persistir PV completa em coluna dedicada (UCI) e derivar SAN a partir do FEN da posição com teste de regressão para garantir múltiplos lances.
- 2026-02-25 - Processo batch sem feedback contínuo de progresso aparentava travamento e exibia traceback ao interromper com Ctrl+C.
  - Causa raiz: progresso era exibido apenas ao fim de cada jogo e não havia tratamento explícito de interrupção do usuário.
  - Prevenção: em rotinas longas, exibir progresso intra-etapa em tempo real (heartbeat visual) e tratar KeyboardInterrupt com encerramento gracioso e resumo parcial.
- 2026-02-22 - Dependência crítica de CDN para tabuleiro (bibliotecas externas) em ambiente com restrição de rede.
  - Causa raiz: frontend dependia de assets remotos para funcionalidade essencial.
  - Prevenção: vendorizar dependências frontend críticas no repositório e servir localmente.
- 2026-02-22 - Feedback de sync insuficiente para usuário.
  - Causa raiz: ausência de estado visual robusto para loading/sucesso/erro no componente de sincronização.
  - Prevenção: manter padrão obrigatório de UX com botão desabilitado durante ação, spinner e mensagem de resultado contextual no próprio bloco.
- 2026-02-22 - Implementação de tabuleiro custom sem necessidade causou regressão visual (tabuleiro sem peças).
  - Causa raiz: tentativa de substituir biblioteca consolidada por implementação própria em vez de vendorizar dependências.
  - Prevenção: priorizar integração de biblioteca estável local (vendorizada) antes de implementar solução custom para componente crítico.
- 2026-02-22 - `chess.js` vendorizado em formato ESM usado como script clássico, quebrando inicialização (`Chess` indefinido).
  - Causa raiz: seleção incorreta do artefato de distribuição JavaScript.
  - Prevenção: validar formato do bundle vendorizado (global/UMD vs ESM) e manter teste de regressão que rejeita `export const Chess` no arquivo usado pelo frontend.

## Política obrigatória de testes
- Ao finalizar qualquer nova feature: criar testes novos cobrindo os novos fluxos e bordas.
- Ao corrigir bug: adicionar teste de regressão que falha antes da correção e passa depois.
- Antes de cada commit: executar toda a suíte de testes.
- O commit só pode seguir se todos os testes passarem.
- Procedimento obrigatório de bugfix: escrever primeiro o teste que reproduz a falha, executar para confirmar falha, aplicar a correção, e executar novamente para confirmar sucesso.

## Comandos padrão
Instalação:
```bash
pip install -r requirements.txt
```

Execução de testes:
```bash
python -m unittest discover -s tests -v
```

Cobertura:
- alvo: cobertura funcional completa do módulo `app.py` e verificação de artefatos web.

## Diretrizes de mudanças
- Não quebrar contratos dos endpoints existentes sem atualizar testes e documentação.
- Ao alterar schema de banco, incluir migração simples/compatível e testes correspondentes.
- Qualquer mudança em UI deve preservar usabilidade mínima: estado de loading, erro e sucesso visíveis.
