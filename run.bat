@echo off
chcp 65001 >nul
rem ---------------------------------------------------------------------------
rem  SSH Drive - запуск приложения
rem  1) создаёт .venv рядом со скриптом (если его нет)
rem  2) ставит зависимости
rem  3) проверяет импорт и запускает GUI без лишнего консольного окна
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
        echo.
        echo Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/
        echo При установке отметьте "Add python.exe to PATH".
        pause
        exit /b 1
    )
    python -m venv "%VENV%"
    if errorlevel 1 goto :error
)

"%PY%" -c "import paramiko, cryptography" >nul 2>&1
if errorlevel 1 (
    echo [2/3] Устанавливаю зависимости...
    "%PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 goto :error
)

rem Проверяем, что код хотя бы импортируется, иначе покажем ошибку в консоли.
"%PY%" -c "import sshdrive.app" 2>nul
if errorlevel 1 (
    echo [3/3] Проверка кода не удалась, запускаю с консолью для диагностики...
    "%PY%" -m sshdrive
    goto :eof
)

echo [3/3] Запускаю SSH Drive...
start "" "%PYW%" -m sshdrive
exit /b 0

:error
echo.
echo Не удалось подготовить окружение. Смотрите сообщения выше.
pause
exit /b 1
