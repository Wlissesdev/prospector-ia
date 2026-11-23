# Plano de execução

## Marco 0 — inspeção e decisões

- [x] Especificação lida integralmente.
- [x] Ambiente identificado: Windows 10, Python 3.12 disponível, CPU Xeon E5-2650 v4.
- [x] Repositório criado em `C:\Users\Wlisses\prospector-ia`.
- [x] Definida arquitetura local com SQLite, Streamlit, pandas e scikit-learn.

## Marco 1 — fundação

- [x] Configuração, logs, banco versionado e scripts Windows.
- [x] Painel navegável e diagnóstico.

## Marco 2 — CRM e importação

- [x] Cadastro, importação CSV, deduplicação, filtros e exportação.

## Descoberta oficial — extensão

- [x] Hashtag → mídia pública oficial, com paginação, limite por execução e filtro de Reels.
- [x] Fila de mídia com proveniência e associação manual do autor quando a API não o retorna.
- [x] Enriquecimento preparado para perfil profissional já conhecido; perfis sugeridos não são expostos pela API oficial.

## Marco 3 — evidências e links

- [x] Evidências, perfis-semente, capturas e análise segura de URLs.

## Marco 4 — revisão e mensagens

- [x] Fila, histórico, opt-out e contatos manuais.

## Marco 5 — aprendizado local

- [x] Treinamento, métricas, versionamento e pré-seleção.

## Marco 6/7 — robustez e entrega

- [x] Backups, testes, documentação e verificação final.

## Riscos e decisões

- O conector Instagram fica desligado até o usuário fornecer credenciais oficiais; não há
  coleta automática, scraping, automação de DM, follow ou like.
- OCR é opcional e não exige Tesseract para a aplicação funcionar.
- A análise de URL só acessa HTTP(S), com bloqueio de endereços locais, privados e reservados.
