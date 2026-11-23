# Prospector IA

Aplicativo local para organizar a prospecção comercial de criadores e influencers. Ele mantém dados, evidências, decisões e aprendizado em um banco SQLite no computador. A interface é em português brasileiro e roda em `localhost`.

O sistema prioriza revisão humana. Ele não raspa Instagram, não armazena senhas, não envia DMs iniciais, não segue nem curte perfis automaticamente.

## Recursos

- cadastro manual e importação CSV com pré-visualização, mapeamento e relatório de erros;
- deduplicação por plataforma e usuário;
- evidências com origem, data, estado de verificação e capturas fornecidas pelo usuário;
- relação entre perfis-semente e candidatos;
- descoberta oficial por hashtag, com coleta paginada de mídia pública, filtro de Reels e fila de associação;
- análise limitada e segura de URLs HTTP(S), com bloqueio de rede local e privada;
- regras editáveis e explicáveis, além de priorização por ML local;
- fila de revisão, histórico auditável e bloqueio de opt-out;
- rascunhos de mensagens, abertura assistida de perfil e registro manual de contato;
- exportação CSV segura para planilhas, backups SQLite e diagnóstico local.

## Requisitos

- Windows 10/11 de 64 bits;
- Python 3.12 (recomendado; Python 3.11 também é compatível);
- cerca de 1 GB livre para o ambiente Python e dados.

## Instalar e executar

No PowerShell, dentro desta pasta:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.ps1
```

Abra o endereço mostrado pelo Streamlit, normalmente `http://localhost:8501`.

Para instalar sem scripts:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Testes e qualidade

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

## Dados e backup

Por padrão, os dados ficam em `%LOCALAPPDATA%\ProspectorIA`. Defina `PROSPECTOR_DATA_DIR` antes de executar para usar outra pasta persistente.

O aplicativo cria um backup automático no máximo uma vez por dia ao abrir e também permite criar um backup manual pela tela **Configurações** ou pelo comando:

```powershell
.\.venv\Scripts\python.exe -m prospector.cli backup
```

Restaure somente um arquivo criado pelo aplicativo e informe `--confirm`:

```powershell
.\.venv\Scripts\python.exe -m prospector.cli restore "C:\caminho\prospector-AAAAMMDDTHHMMSSZ.sqlite3" --confirm
```

Consulte os guias em [docs](docs/).
