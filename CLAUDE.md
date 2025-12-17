# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

AWS EC2 인스턴스 관리 CLI 도구 및 웹 버전. SSM 터미널, RDS 연결, ECS 관리 등 통합 관리 기능 제공.

## Project Structure

```
ec2menu_script/
├── ec2menu_latest.py      # CLI 최신 버전 (사용)
├── ec2menu_v*.py          # 버전별 히스토리
├── web-version/           # 웹 애플리케이션 버전
│   ├── backend/           # FastAPI 백엔드
│   └── frontend/          # React 프론트엔드
└── web_gui/               # 레거시 웹 GUI
```

## Common Commands

### CLI 실행

```bash
python ec2menu_latest.py
```

### 웹 버전 실행 (Docker)

```bash
cd web-version
docker-compose up -d --build

# 접속
# 웹 앱: http://localhost:8080
# API 문서: http://localhost:8000/docs
```

## Features

- EC2 인스턴스 목록 조회 및 관리
- SSM 터미널 접속
- RDS 데이터베이스 연결
- ECS 컨테이너 관리
- ElastiCache 클러스터 연결
- S3 경유 파일 전송
- 연결 히스토리 및 캐싱

## Web Version Architecture

```
Frontend (React + Vite)
    ↓ HTTP/WebSocket
Backend (FastAPI)
    ↓ boto3
AWS Services (EC2, RDS, ECS, SSM)
```

## Version Convention

- `ec2menu_latest.py` - 항상 최신 안정 버전
- `ec2menu_v{major}.{minor}.{patch}.py` - 버전별 스냅샷
- 개발 시 최신 버전 기반으로 작업, 완료 후 버전 파일 생성
