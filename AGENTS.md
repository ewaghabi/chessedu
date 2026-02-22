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

## Política obrigatória de testes
- Ao finalizar qualquer nova feature: criar testes novos cobrindo os novos fluxos e bordas.
- Ao corrigir bug: adicionar teste de regressão que falha antes da correção e passa depois.
- Antes de cada commit: executar toda a suíte de testes.
- O commit só pode seguir se todos os testes passarem.

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
