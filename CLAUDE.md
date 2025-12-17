# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

AWS EC2 인스턴스 관리 CLI 도구 및 웹 버전. SSM 터미널, RDS 연결, ECS 관리 등 통합 관리 기능 제공.

## Project Structure

```
ec2menu_script/
├── ec2menu_v5.2.0_mac.py  # CLI 최신 버전 (macOS 전용)
├── ec2menu_v*.py          # 버전별 히스토리
├── web-version/           # 웹 애플리케이션 버전
│   ├── backend/           # FastAPI 백엔드
│   └── frontend/          # React 프론트엔드
├── web_gui/               # 레거시 웹 GUI
├── README_mac.md          # macOS 버전 사용 가이드
├── dev_ec2menu_v4.41_to_v5.1.9.md  # Windows 버전 개발 히스토리
└── work_history_v5.2.0_mac.md      # macOS 버전 작업 기록
```

## Current Version

### v5.2.0 - macOS 전용 버전

- Windows v5.1.9에서 포팅
- macOS 네이티브 지원 (iTerm2/Terminal.app)
- WSL 코드 제거 및 경로 처리 개선
- 배치 작업 재시도 로직 강화

## Common Commands

### CLI 실행

```bash
# macOS 최신 버전
python3 ec2menu_v5.2.0_mac.py

# 또는 실행 권한 부여 후
chmod +x ec2menu_v5.2.0_mac.py
./ec2menu_v5.2.0_mac.py
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

### Core Features

- EC2 인스턴스 목록 조회 및 관리
- SSM 터미널 접속 (Linux/Windows RDP)
- RDS 데이터베이스 연결
- ECS 컨테이너 관리 (Fargate 지원)
- ElastiCache 클러스터 연결
- S3 경유 파일 전송 (80MB+ 대용량)
- 연결 히스토리 및 캐싱

### Advanced Features

- **배치 작업**: 여러 인스턴스 동시 명령 실행
  - 자동 재시도 (최대 3회, 10s/20s/30s 점진적 대기)
  - 실패 인스턴스 선택적 재시도
  - 실시간 진행률 표시
- **멀티 리전**: 여러 AWS 리전 동시 관리
- **캐싱 시스템**: 빠른 응답 속도
- **macOS 통합**: iTerm2/Terminal.app 자동 탭 열기

## Web Version Architecture

```
Frontend (React + Vite)
    ↓ HTTP/WebSocket
Backend (FastAPI)
    ↓ boto3
AWS Services (EC2, RDS, ECS, SSM)
```

## Version Convention

- `ec2menu_v{major}.{minor}.{patch}_mac.py` - macOS 버전별 스냅샷
- `ec2menu_v{major}.{minor}.{patch}.py` - Windows/WSL 버전별 스냅샷
- 개발 시 최신 버전 기반으로 작업, 완료 후 버전 파일 생성

## Development Guidelines

### Commit Convention

```bash
# 기능 추가
feat: 배치 작업 재시도 로직 강화

# 버그 수정
fix: 배치 작업 재시도 로직 완전 수정

# 리팩토링
refactor: P1 보안 및 안정성 개선

# 보안
security: DB 비밀번호 마스킹 처리
```

### Code Quality Standards

- Python 3.9+ 호환성 (`from __future__ import annotations`)
- PEP 8 준수 (import 순서, 줄 길이)
- Type hints 사용 권장
- Thread-safe 코드 (threading.Lock)
- 상세한 에러 처리 및 로깅

### Testing Checklist

- [ ] Python 구문 체크: `python3 -m py_compile ec2menu_v5.2.0_mac.py`
- [ ] EC2 인스턴스 접속 테스트
- [ ] 배치 작업 테스트 (재시도 포함)
- [ ] 파일 전송 테스트
- [ ] 멀티 리전 전환 테스트

## Work History

작업 기록은 `work_history_v5.2.0_mac.md` 참조
