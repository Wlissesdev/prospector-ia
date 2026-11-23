# Relatório de verificação — 2026-10-09

## Ambiente

- Windows 10 64 bits (10.0.19045);
- Python 3.12.10;
- CPU Intel Xeon E5-2650 v4;
- dependências fixadas em `requirements.txt`.

## Resultados reais

| Verificação | Resultado |
| --- | --- |
| `python -m pytest -vv` | 24 testes passaram |
| Importação de 1.000 registros sintéticos | passou em 1,78 s no teste; 2,438 s incluindo inicialização do pytest |
| `python -m ruff check .` | sem erros |
| `python -m compileall -q app.py src` | sem erros |
| Streamlit `AppTest` | carregou o painel sem exceções; título da barra lateral: `Prospector IA` |

Os testes incluem CSV válido e inválido, fórmulas em campos de identificação, URLs locais e protocolos perigosos, deduplicação, evidências, relações de descoberta, descoberta oficial por hashtag com paginação simulada, associação manual de autor, opt-out, mensagens preparadas, exclusão lógica, pré-seleção em lote, correção humana de links, backup manual/automático/restauração, modelo com uma classe, treinamento com dados sintéticos, 1.000 registros e presença das rotas principais da interface.

Dados usados nos testes são sintéticos e não aparecem no modo normal do aplicativo.
