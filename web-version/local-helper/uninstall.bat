@echo off
echo EC2Menu RDP Helper 제거 중...

REM 레지스트리에서 URL 스키마 제거
echo 레지스트리에서 ec2rdp:// URL 스키마 제거 중...

reg delete "HKEY_CLASSES_ROOT\ec2rdp" /f 2>nul

if errorlevel 1 (
    echo 경고: 레지스트리 제거에 실패했거나 이미 제거되었습니다.
) else (
    echo ✅ URL 스키마가 성공적으로 제거되었습니다.
)

echo.
echo EC2Menu RDP Helper 제거 완료!
echo.

pause