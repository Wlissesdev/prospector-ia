# Instalação no Windows

1. Instale o Python 3.12 pela Microsoft Store ou por `python.org`. Durante a instalação, habilite o Python Launcher (`py`).
2. Abra o PowerShell na pasta `prospector-ia`.
3. Execute `Set-ExecutionPolicy -Scope Process Bypass` somente para a janela atual caso a política bloqueie scripts.
4. Execute `.\setup.ps1`.
5. Execute `.\run.ps1` e abra o endereço local indicado.

Para atualizar o projeto, faça um backup pela tela **Configurações**, atualize os arquivos e execute `.\setup.ps1` novamente. O banco não fica dentro da pasta do código por padrão; ele permanece em `%LOCALAPPDATA%\ProspectorIA`.

Se a porta 8501 estiver ocupada, inicie manualmente com:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502
```
