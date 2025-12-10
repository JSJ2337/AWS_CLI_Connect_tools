@echo off
chcp 65001 > nul
echo Starting EC2Menu Web Version...

REM Check AWS credentials
echo.
echo Checking AWS credentials...
if not exist "%USERPROFILE%\.aws\credentials" (
    echo ERROR: AWS credentials not found.
    echo.
    echo Please set up AWS credentials using one of these methods:
    echo.
    echo 1. AWS CLI setup:
    echo    aws configure
    echo.
    echo 2. Environment variables:
    echo    set AWS_ACCESS_KEY_ID=your_access_key
    echo    set AWS_SECRET_ACCESS_KEY=your_secret_key
    echo.
    echo 3. Create AWS credentials file:
    echo    %USERPROFILE%\.aws\credentials
    echo.
    pause
    exit /b 1
)

echo OK: AWS credentials found.

REM Check Docker
echo.
echo Checking Docker status...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not installed or not running.
    echo.
    echo Please install Docker Desktop and run it.
    echo Download: https://www.docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)

docker ps >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not running.
    echo.
    echo Please start Docker Desktop and try again.
    echo.
    pause
    exit /b 1
)

echo OK: Docker is running.

REM Clean up existing containers
echo.
echo Cleaning up existing containers...
docker-compose down --remove-orphans

REM Build and start services
echo.
echo Building Docker images and starting services...
docker-compose up -d --build

REM Check service status
echo.
echo Checking service status...
timeout /t 10 >nul

docker-compose ps

echo.
echo SUCCESS: EC2Menu Web is now running!
echo.
echo Web Application: http://localhost:8080
echo Backend API: http://localhost:8000
echo System Status: http://localhost:8000/api/status
echo.
echo Usage:
echo - Open http://localhost:8080 in your browser
echo - Select AWS profile and region
echo - Connect to EC2 instances via terminal or RDP
echo.
echo To stop services: docker-compose down
echo To view logs: docker-compose logs -f
echo.

REM Open browser automatically
echo Opening browser...
start http://localhost:8080

pause