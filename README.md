# AWS CLI Connect Tools

AWS 리소스(EC2, RDS, ECS) 접속 및 관리를 위한 CLI 도구 모음

## 개요

AWS 인프라의 다양한 리소스에 빠르고 편리하게 접속하기 위한 CLI 도구입니다.
EC2 인스턴스, RDS 데이터베이스, ECS 컨테이너 등에 대한 연결을 자동화하고,
복잡한 AWS CLI 명령어를 간단한 메뉴 인터페이스로 제공합니다.

## 주요 기능

### EC2 Menu (ec2menu)

EC2 인스턴스 접속을 위한 대화형 메뉴 시스템

**지원 기능**:

- AWS 프로파일 자동 감지 및 선택
- 리전별 EC2 인스턴스 목록 조회
- SSH, SSM Session Manager 접속
- Windows RDP 연결
- 인스턴스 상태 확인 및 시작/중지
- HeidiSQL을 통한 RDS 접속

**버전 히스토리**:

- v5.x: 최신 버전 (멀티 프로파일, 리전 지원 강화)
- v4.x: Windows Terminal 통합, RDP 지원
- v3.x: SSM Session Manager 통합
- v2.x: 멀티 리전 지원
- v1.x: 초기 버전

### 사전 준비사항

**필수 요구사항**:

- Python 3.8 이상
- AWS CLI v2
- boto3 Python 라이브러리
- Session Manager Plugin

**선택 사항**:

- Windows Terminal (Windows 환경)
- WSL2 (Windows 환경에서 권장)

## 설치

### 1. Python 패키지 설치

```bash
pip install boto3
```

### 2. AWS CLI 설정

```bash
aws configure
```

### 3. Session Manager Plugin 설치

```bash
# macOS
brew install --cask session-manager-plugin

# Linux
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb
```

## 사용 방법

### 기본 실행

```bash
# 최신 버전 실행
python3 ec2menu_latest.py

# 특정 프로파일 지정
python3 ec2menu_latest.py --profile production

# 특정 리전 지정
python3 ec2menu_latest.py --region ap-northeast-2

# 디버그 모드
python3 ec2menu_latest.py --debug
```

### 메뉴 사용 예제

```text
1. AWS 프로파일 선택
2. 리전 선택
3. EC2 인스턴스 목록 조회
4. 접속 방식 선택 (SSH/SSM/RDP)
5. 연결
```

## 파일 구조

```text
AWS_CLI_Connect_tools/
├── ec2menu_latest.py              # 최신 버전
├── ec2menu_v5.x.py                # 버전별 스크립트
├── ec2menu_v4.x.py
├── ec2menu_v3.x.py
├── ec2menu_v2.x.py
├── ec2menu_v1.x.py
└── *.md                           # 개발 히스토리 및 마이그레이션 문서
```

## 주요 기능 상세

### 1. 프로파일 관리

- `~/.aws/credentials` 및 `~/.aws/config` 자동 파싱
- 멀티 프로파일 지원
- 프로파일별 기본 리전 설정

### 2. 인스턴스 검색

- Name 태그 기반 검색
- 인스턴스 ID 검색
- Private/Public IP 표시
- 상태별 필터링

### 3. 접속 방식

- **SSH**: Private Key 기반 접속
- **SSM**: Session Manager를 통한 안전한 접속 (보안그룹 불필요)
- **RDP**: Windows 인스턴스 원격 데스크톱

### 4. RDS 연결

- HeidiSQL 자동 실행
- Bastion 호스트를 통한 터널링
- 연결 설정 자동 구성

## 보안 고려사항

- Private Key 파일은 600 권한 유지 필수
- AWS Credentials는 절대 코드에 하드코딩 금지
- SSM Session Manager 사용 권장 (보안그룹 22번 포트 오픈 불필요)
- MFA 설정된 프로파일 지원

## 트러블슈팅

### Session Manager Plugin 오류

```bash
# Plugin 설치 확인
session-manager-plugin --version
```

### AWS 프로파일 인식 안됨

```bash
# 프로파일 확인
aws configure list-profiles

# 특정 프로파일 테스트
aws ec2 describe-instances --profile your-profile
```

### Python 모듈 없음

```bash
pip install --upgrade boto3
```

## 개발 히스토리

상세한 개발 히스토리 및 마이그레이션 가이드는 다음 문서를 참고하세요:

- `dev_ec2menu_v4.41_to_v5.1.2.md`: v4 → v5 마이그레이션
- `ec2menu_mac_migration_summary.md`: macOS 환경 마이그레이션

## 라이선스

Private Repository

## 기여

내부 사용 목적의 Private 저장소입니다.
