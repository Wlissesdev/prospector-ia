$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    throw 'Ambiente virtual não encontrado. Execute .\setup.ps1 primeiro.'
}

& .\.venv\Scripts\python.exe -m streamlit run app.py
