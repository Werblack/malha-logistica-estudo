@echo off
setlocal
cd /d "%~dp0"

if not exist "requirements.txt" (
    echo ERRO: requirements.txt nao foi encontrado nesta pasta.
    echo Extraia o ZIP inteiro antes de executar este arquivo.
    echo Nao execute o BAT de dentro do arquivo ZIP.
    pause
    exit /b 1
)

echo Malha Logistica SP
echo.

where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo Python 3.12 ou superior nao foi encontrado.
        echo Instale Python em https://www.python.org/downloads/windows/
        pause
        exit /b 1
    )
    set "PYTHON_CMD=py -3"
) else (
    set "PYTHON_CMD=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :erro
)

echo Instalando ou atualizando dependencias...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :erro

.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 goto :erro

if not exist "data\processed\os.parquet" (
    echo Preparando os dados. Esta etapa pode levar alguns minutos...
    .venv\Scripts\python.exe -m malha.build --offline
    if errorlevel 1 goto :erro
)

echo Iniciando o aplicativo...
.venv\Scripts\python.exe desktop\main.py
if errorlevel 1 goto :erro
exit /b 0

:erro
echo.
echo O aplicativo nao conseguiu iniciar. A mensagem acima indica o problema.
pause
exit /b 1