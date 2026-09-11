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

set "APP_ENV=%LOCALAPPDATA%\MalhaLogistica\.venv"

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

if not exist "%APP_ENV%\Scripts\python.exe" (
    echo Criando ambiente virtual...
    if exist "%APP_ENV%" rmdir /s /q "%APP_ENV%"
    %PYTHON_CMD% -m venv "%APP_ENV%"
    if errorlevel 1 goto :erro
)

echo Instalando ou atualizando dependencias...
"%APP_ENV%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :erro

"%APP_ENV%\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :erro

if not exist "data\processed\os.parquet" (
    echo Preparando os dados. Esta etapa pode levar alguns minutos...
    "%APP_ENV%\Scripts\python.exe" -m malha.build --offline
    if errorlevel 1 goto :erro
)

echo Iniciando o aplicativo...
"%APP_ENV%\Scripts\python.exe" desktop\main.py
if errorlevel 1 goto :erro
exit /b 0

:erro
echo.
echo O aplicativo nao conseguiu iniciar. A mensagem acima indica o problema.
pause
exit /b 1