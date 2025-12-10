#!/bin/bash

echo "🚀 EC2Menu Web 버전을 시작합니다..."

# AWS 자격증명 확인
echo ""
echo "📋 AWS 자격증명을 확인 중..."
if [ ! -f "$HOME/.aws/credentials" ]; then
    echo "❌ AWS 자격증명이 설정되지 않았습니다."
    echo ""
    echo "다음 중 하나의 방법으로 AWS 자격증명을 설정해주세요:"
    echo ""
    echo "1. AWS CLI 설정:"
    echo "   aws configure"
    echo ""
    echo "2. 환경변수 설정:"
    echo "   export AWS_ACCESS_KEY_ID=your_access_key"
    echo "   export AWS_SECRET_ACCESS_KEY=your_secret_key"
    echo ""
    echo "3. AWS 자격증명 파일 생성:"
    echo "   ~/.aws/credentials"
    echo ""
    exit 1
fi

echo "✅ AWS 자격증명이 확인되었습니다."

# Docker 확인
echo ""
echo "🐳 Docker 상태를 확인 중..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker가 설치되지 않았습니다."
    echo ""
    echo "Docker를 설치한 후 다시 시도해주세요."
    echo "설치 방법: https://docs.docker.com/get-docker/"
    echo ""
    exit 1
fi

if ! docker ps &> /dev/null; then
    echo "❌ Docker가 실행되지 않습니다."
    echo ""
    echo "Docker를 시작한 후 다시 시도해주세요."
    echo "명령어: sudo systemctl start docker"
    echo ""
    exit 1
fi

echo "✅ Docker가 정상적으로 실행 중입니다."

# 기존 컨테이너 정리
echo ""
echo "🧹 기존 컨테이너를 정리 중..."
docker-compose down --remove-orphans

# Docker 이미지 빌드 및 실행
echo ""
echo "🏗️ Docker 이미지를 빌드하고 서비스를 시작합니다..."
docker-compose up -d --build

# 서비스 상태 확인
echo ""
echo "🔍 서비스 상태를 확인 중..."
sleep 10

docker-compose ps

echo ""
echo "🎉 EC2Menu Web이 성공적으로 시작되었습니다!"
echo ""
echo "📱 웹 애플리케이션 접속:"
echo "   http://localhost:8080"
echo ""
echo "🔧 백엔드 API 접속:"
echo "   http://localhost:8000"
echo ""
echo "📊 시스템 상태 확인:"
echo "   http://localhost:8000/api/status"
echo ""
echo "💡 사용법:"
echo "   - 브라우저에서 http://localhost:8080 에 접속"
echo "   - AWS 프로파일과 리전을 선택"
echo "   - EC2 인스턴스 목록에서 터미널 또는 RDP 연결"
echo ""
echo "🛑 서비스 중지:"
echo "   docker-compose down"
echo ""
echo "📝 로그 확인:"
echo "   docker-compose logs -f"
echo ""

# 브라우저 자동 열기 (Linux/Mac)
if command -v xdg-open &> /dev/null; then
    echo "🌐 브라우저를 자동으로 엽니다..."
    xdg-open http://localhost:8080
elif command -v open &> /dev/null; then
    echo "🌐 브라우저를 자동으로 엽니다..."
    open http://localhost:8080
fi