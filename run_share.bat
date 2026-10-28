@echo off
chcp 65001 >nul
rem ---------------------------------------------------------------------------
rem  SSH Share - запуск программы «общий доступ к папке по SSH»
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"

if not exist "%PY%" (
    echo [1/3] Создаю виртуальное окружение...
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/
        if not defined SSHDRIVE_NO_PAUSE pause
        exit /b 1
    )
    python -m venv "%VENV%"
    if errorlevel 1 goto :error
)

"%PY%" -c "import asyncssh, paramiko, cryptography, pystray, PIL" >nul 2>&1
if errorlevel 1 (
    echo [2/3] Устанавливаю зависимости...
    "%PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 goto :error
)

"%PY%" -c "import ssh_share.app" 2>nul
if errorlevel 1 (
    echo [3/3] Проверка кода не удалась, запускаю с консолью для диагностики...
    "%PY%" -m ssh_share
    goto :eof
)

echo [3/3] Запускаю SSH Share...
start "" "%PYW%" -m ssh_share
exit /b 0

:error
echo.
echo Не удалось подготовить окружение. Смотрите сообщения выше.
if not defined SSHDRIVE_NO_PAUSE pause
exit /b 1
