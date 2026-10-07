@echo off
REM PC 수집기 실행 (윈도우). 더블클릭하면 실행됩니다. 창을 닫으면 종료됩니다.
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title VALORANT 봇 - PC 수집기

REM 쓸 수 있는 파이썬 찾기
set "PY="
for %%C in ("py -3.12" "py -3" "%USERPROFILE%\miniconda3\python.exe" "%USERPROFILE%\anaconda3\python.exe" "python") do (
    if not defined PY (
        %%~C -c "import sys; assert sys.version_info >= (3, 9)" > nul 2>&1 && set "PY=%%~C"
    )
)
if not defined PY goto :nopython
echo [준비] 사용할 파이썬: %PY%

REM 수집기는 패키지 2개뿐이라 가상환경 없이 사용자 영역(--user)에 설치합니다.
%PY% -c "import aiohttp, dotenv" > nul 2>&1
if errorlevel 1 (
    echo [준비] 필요한 패키지를 설치합니다 ^(처음 한 번만^)...
    %PY% -m pip install --user -r requirements-worker.txt || goto :error
)

if not exist ".env" (
    echo [오류] .env 파일이 없습니다. .env.example 을 복사해서 .env 로 이름을 바꾸고
    echo        WORKER_TOKEN 과 BOT_URL 을 채워주세요.
    pause
    exit /b 1
)

%PY% -m bot.local_worker
pause
exit /b 0

:nopython
echo [오류] 파이썬을 찾지 못했습니다.
echo        https://www.python.org/downloads/ 에서 Python 3.12 를 설치하세요.
echo        설치 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크하세요.
pause
exit /b 1

:error
echo [오류] 패키지 설치 중 문제가 생겼습니다. 위 메시지를 확인해주세요.
pause
exit /b 1
