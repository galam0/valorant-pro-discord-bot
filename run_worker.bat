@echo off
REM PC 수집기 실행 (윈도우). 더블클릭하면 실행됩니다. 창을 닫으면 종료됩니다.
chcp 65001 > nul
cd /d "%~dp0"
title VALORANT 봇 - PC 수집기

if not exist ".venv\Scripts\python.exe" (
    echo [준비] 처음 실행이라 가상환경을 만들고 패키지를 설치합니다...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip > nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

if not exist ".env" (
    echo [오류] .env 파일이 없습니다. .env.example 을 복사해서 BOT_URL 과 WORKER_TOKEN 을 채워주세요.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m bot.local_worker
pause
exit /b 0

:error
echo [오류] 설치 중 문제가 생겼습니다. Python 3.12 가 설치되어 있는지 확인해주세요.
pause
exit /b 1
