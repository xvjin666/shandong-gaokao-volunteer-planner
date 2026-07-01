@echo off
setlocal EnableExtensions

set "APP_DIR=%~dp0"
set "DB_PATH=%APP_DIR%data\sample\open_demo.sqlite"
set "URL=http://127.0.0.1:8765/"
set "PY_EXE="

cd /d "%APP_DIR%"

if exist "%APP_DIR%runtime\python\python.exe" (
  set "PY_EXE=%APP_DIR%runtime\python\python.exe"
) else (
  where py >nul 2>nul
  if not errorlevel 1 set "PY_EXE=py"
)

if "%PY_EXE%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 set "PY_EXE=python"
)

if "%PY_EXE%"=="" (
  echo 未找到 Python。请安装 Python 3.9 及以上版本。
  pause
  exit /b 1
)

set "PYTHONPATH=%APP_DIR%src"

if not exist "%DB_PATH%" (
  echo 正在用开源样例数据创建 SQLite 数据库...
  "%PY_EXE%" -m gaokao_decision.cli build-sample-db --db "%DB_PATH%"
  if errorlevel 1 (
    echo 样例数据库创建失败。
    pause
    exit /b 1
  )
)

echo 正在启动本地样例服务...
start "Gaokao Planner Sample Server" /min cmd /c ""%PY_EXE%" "%APP_DIR%scripts\serve_app.py" --db "%DB_PATH%" --host 127.0.0.1 --port 8765"

timeout /t 2 /nobreak >nul
start "" "%URL%"
echo 已启动。若浏览器未自动打开，请访问 %URL%
timeout /t 3 /nobreak >nul
