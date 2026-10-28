@echo off
chcp 65001 >nul
rem ---------------------------------------------------------------------------
rem  Сборка самодостаточных exe (PyInstaller, onefile, без консоли)
rem
rem   dist\SSHDrive.exe         ~20 МБ: Python и библиотеки внутри,
rem                             rclone и WinFsp скачиваются при первом запуске
rem   dist\SSHDrive-offline.exe ~60 МБ: плюс встроенные rclone.exe и MSI WinFsp
rem
rem  Нужен Python 3.10+ (лучше 3.13) и интернет для установки зависимостей.
rem  Зависимости и PyInstaller закреплены с хэшами (requirements*.txt).
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "BASEPY="
py -3.13 -c "import sys" >nul 2>&1 && set "BASEPY=py -3.13"
if not defined BASEPY py -3 -c "import sys" >nul 2>&1 && set "BASEPY=py -3"
if not defined BASEPY python -c "import sys" >nul 2>&1 && set "BASEPY=python"
if not defined BASEPY (
    echo Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/
    if not defined SSHDRIVE_NO_PAUSE pause
    exit /b 1
)

set "VENV=%~dp0.venv-build"
set "BPY=%VENV%\Scripts\python.exe"

if not exist "%BPY%" (
    echo [1/5] Создаю окружение сборки...
    %BASEPY% -m venv "%VENV%"
    if errorlevel 1 goto :error
)

echo [2/5] Устанавливаю зависимости...
"%BPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%BPY%" -m pip install --disable-pip-version-check -q -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :error

echo [3/5] Рисую иконку...
"%BPY%" tools\make_icon.py
if errorlevel 1 goto :error

echo [4/5] Собираю обычную версию...
set "SSHDRIVE_BUNDLE_TOOLS="
set "SSHDRIVE_EXE_NAME=SSHDrive"
"%BPY%" -m PyInstaller --noconfirm --distpath dist --workpath build\pyi-light sshdrive.spec
if errorlevel 1 goto :error

echo [5/5] Собираю offline-версию (rclone + WinFsp внутри)...
set "SSHDRIVE_BUNDLE_TOOLS=1"
set "SSHDRIVE_EXE_NAME=SSHDrive-offline"
"%BPY%" tools\fetch_tools.py
if errorlevel 1 (
    echo.
    echo Не удалось скачать rclone/WinFsp — offline-сборка пропущена.
    goto :done
)
"%BPY%" -m PyInstaller --noconfirm --distpath dist --workpath build\pyi-offline sshdrive.spec
if errorlevel 1 goto :error

:done
echo.
echo Готово. Файлы:
dir /b dist\*.exe
echo.
if not defined SSHDRIVE_NO_PAUSE pause
exit /b 0

:error
echo.
echo Сборка не удалась. Смотрите сообщения выше.
if not defined SSHDRIVE_NO_PAUSE pause
exit /b 1
