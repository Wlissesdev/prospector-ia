# Rastreabilidade da especificação

Este projeto implementa a especificação `Prospector_IA_Especificacao_Completa.md` fornecida pelo usuário em 2026-10-09.

| Área da especificação | Implementação |
| --- | --- |
| CRM, persistência e deduplicação | SQLite versionado e `Repository` |
| Importação, exportação e CSV seguro | `services/import_service.py`, tela Importação/exportação |
| Evidências, Stories fornecidos e capturas | tabela `evidence`, tela Evidências e Links |
| Links e SSRF | `utils/urls.py`, com bloqueio de destinos locais/privados |
| Perfis-semente | tabela `seed_relations` e tela de relações |
| Revisão e opt-out | `review_events`, fila de revisão e bloqueio de contato |
| Mensagens sem envio automático | `outreach` e tela Mensagens |
| ML local | `analysis/ml_pipeline.py`, artefato local versionado |
| Backup, logs e diagnóstico | `database/backup.py`, logs rotativos e tela Diagnóstico |

## Limites intencionais

- O conector de Instagram apenas valida se as variáveis de ambiente oficiais foram configuradas. Ele não afirma acesso a dados e não foi testado sem credenciais e permissões reais.
- A entrada de Stories, sugestões e métricas é assistida: o usuário registra dados ou evidências a que tem direito de acesso.
- OCR não é requisito da versão base. Capturas são armazenadas com origem explícita; o texto pode ser inserido pelo usuário.
- A análise de URL é opcional e só acontece ao clicar no comando da tela. Ela não executa JavaScript, nem envia cookies ou credenciais.
