@echo off
echo EC2Menu RDP Helper 설치 중...

REM 현재 디렉토리 경로 가져오기
set CURRENT_DIR=%~dp0

REM Python 실행파일 경로 설정
set PYTHON_EXE=python.exe
set HELPER_SCRIPT=%CURRENT_DIR%ec2rdp_helper.py

REM Python이 설치되어 있는지 확인
python.exe --version >nul 2>&1
if errorlevel 1 (
    echo 오류: Python이 설치되어 있지 않습니다.
    echo Python 3.7 이상을 설치한 후 다시 시도하세요.
    pause
    exit /b 1
)

REM 헬퍼 스크립트가 존재하는지 확인
if not exist "%HELPER_SCRIPT%" (
    echo 오류: ec2rdp_helper.py 파일을 찾을 수 없습니다.
    echo 현재 디렉토리: %CURRENT_DIR%
    pause
    exit /b 1
)

echo Python 경로: %PYTHON_EXE%
echo 헬퍼 스크립트: %HELPER_SCRIPT%

REM 레지스트리에 URL 스키마 등록
echo 레지스트리에 ec2rdp:// URL 스키마 등록 중...

reg add "HKEY_CLASSES_ROOT\ec2rdp" /ve /d "EC2Menu RDP Protocol" /f
reg add "HKEY_CLASSES_ROOT\ec2rdp" /v "URL Protocol" /d "" /f
reg add "HKEY_CLASSES_ROOT\ec2rdp\DefaultIcon" /ve /d "\"%PYTHON_EXE%\",1" /f
reg add "HKEY_CLASSES_ROOT\ec2rdp\shell" /f
reg add "HKEY_CLASSES_ROOT\ec2rdp\shell\open" /f
reg add "HKEY_CLASSES_ROOT\ec2rdp\shell\open\command" /ve /d "\"%PYTHON_EXE%\" \"%HELPER_SCRIPT%\" \"%%1\"" /f

if errorlevel 1 (
    echo 오류: 레지스트리 등록에 실패했습니다.
    echo 관리자 권한으로 실행해주세요.
    pause
    exit /b 1
)

echo.
echo ✅ EC2Menu RDP Helper 설치 완료!
echo.
echo 이제 웹 브라우저에서 ec2rdp:// 링크를 클릭하면
echo 자동으로 Windows RDP 클라이언트가 실행됩니다.
echo.
echo 테스트: ec2rdp://localhost:3389
echo.

pause