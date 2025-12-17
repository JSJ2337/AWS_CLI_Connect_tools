# EC2Menu v5.2.0 - macOS 버전

AWS EC2/RDS/ElastiCache/ECS 접속 자동화 스크립트 (macOS 전용)

## 🍎 macOS 전용 기능

### v5.2.0 신규 기능
- **iTerm2/Terminal.app 통합**: 새 터미널 탭에서 자동으로 접속
- **FreeRDP 지원**: Windows 인스턴스에 RDP 접속
- **경로 정규화**: macOS 네이티브 파일 경로 처리
- **WSL 코드 제거**: 깔끔한 macOS 전용 코드베이스

### 기존 기능 유지
- S3 경유 대용량 파일 전송 (80MB+)
- 배치 작업 (여러 인스턴스 동시 명령 실행)
- 멀티 리전 지원
- 연결 히스토리 관리
- 컬러 테마 (상태별 색깔 구분)

## 📦 설치

### 1. 필수 요구사항

```bash
# Homebrew (macOS 패키지 매니저)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# AWS CLI 설치
brew install awscli

# AWS CLI 설정
aws configure
```

### 2. Python 패키지 설치

```bash
# boto3, colorama 설치
pip3 install --break-system-packages boto3 colorama

# 또는 venv 사용 (권장)
python3 -m venv venv
source venv/bin/activate
pip install boto3 colorama
```

### 3. 선택 사항 (권장)

#### iTerm2 설치 (더 나은 터미널 경험)

```bash
brew install --cask iterm2
```

#### Windows RDP 클라이언트 (Windows 서버 접속용)

App Store에서 **"Microsoft Remote Desktop"** 또는 **"Windows App"** 설치 (무료)

- 스크립트가 자동으로 .rdp 파일을 생성하여 연결

## 🚀 사용법

### 기본 실행

```bash
# 실행 권한 부여 (최초 1회)
chmod +x ec2menu_v5.2.0_mac.py

# 스크립트 실행
python3 ec2menu_v5.2.0_mac.py

# 또는 직접 실행
./ec2menu_v5.2.0_mac.py
```

### 옵션

```bash
# 특정 AWS 프로파일 사용
python3 ec2menu_v5.2.0_mac.py -p my-profile

# 특정 리전 지정
python3 ec2menu_v5.2.0_mac.py -r ap-northeast-2

# 디버그 모드
python3 ec2menu_v5.2.0_mac.py -d
```

## 🔧 환경 변수

```bash
# ~/.zshrc 또는 ~/.bash_profile에 추가

# 데이터베이스 도구 경로 (선택)
export DB_TOOL_PATH="mysql"  # 또는 "sequel-ace", "tableplus" 등

# Redis CLI 경로
export CACHE_REDIS_CLI="redis-cli"

# Memcached CLI 경로
export CACHE_MEMCACHED_CLI="telnet"
```

## 📋 주요 기능

### 1. EC2 인스턴스 접속
- **Linux 인스턴스**: SSM Session Manager로 접속
- **Windows 인스턴스**: RDP 포트 포워딩 후 FreeRDP로 접속
- **iTerm2/Terminal.app**: 새 탭에서 자동으로 접속

### 2. 파일 전송
- **S3 경유 전송**: 대용량 파일 (80MB+) 안전 전송
- **배치 전송**: 여러 인스턴스에 동시 배포
- **진행률 표시**: 실시간 전송 상태 확인

### 3. 배치 작업
- 여러 인스턴스에 동시에 명령 실행
- SSM Run Command 활용
- 실행 결과 수집 및 표시

### 4. RDS/ElastiCache 접속
- 점프 호스트 자동 선택 (Role=jumphost 태그)
- 포트 포워딩 자동 설정
- 로컬 클라이언트 자동 실행

### 5. ECS Fargate 컨테이너 접속
- ECS Exec을 통한 컨테이너 쉘 접속
- 새 터미널 탭에서 실행

## 🎯 사용 예시

### EC2 Linux 인스턴스 접속
1. 스크립트 실행
2. AWS 프로파일 선택
3. 리전 선택
4. `1. EC2` 선택
5. 접속할 인스턴스 번호 입력
6. iTerm2/Terminal.app 새 탭에서 자동 접속

### Windows 인스턴스 RDP 접속
1. EC2 메뉴에서 Windows 인스턴스 선택
2. 자동으로 RDP 포트 포워딩 시작
3. FreeRDP가 자동으로 실행됨
4. Administrator 계정으로 로그인

### 파일 전송
1. EC2 메뉴에서 `f. 파일 업로드` 선택
2. 로컬 파일 경로 입력 (드래그앤드롭 가능)
3. 원격 경로 입력 (예: `/tmp/myfile.zip`)
4. 전송 대상 인스턴스 선택
5. 확인 후 전송 시작

## ⚙️ macOS 터미널 설정

### iTerm2를 기본 터미널로 사용
스크립트는 iTerm2가 설치되어 있으면 자동으로 사용합니다.

### Terminal.app 사용
iTerm2가 없으면 자동으로 Terminal.app을 사용합니다.

## 🐛 문제 해결

### Windows RDP 연결 문제

```bash
# RDP 클라이언트 설치 확인
ls /Applications | grep -i "remote\|windows"

# App Store에서 설치 권장:
# - "Microsoft Remote Desktop" (무료)
# - "Windows App" (무료, Microsoft 최신 버전)
```

### boto3 import 오류
```bash
# Python 버전 확인
python3 --version

# boto3 설치 확인
python3 -c "import boto3; print(boto3.__version__)"

# 재설치
pip3 install --break-system-packages --force-reinstall boto3
```

### AWS CLI 오류
```bash
# AWS CLI 설치 확인
which aws

# AWS 자격증명 확인
aws configure list

# SSM 플러그인 설치
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/mac_arm64/sessionmanager-bundle.zip" -o "sessionmanager-bundle.zip"
unzip sessionmanager-bundle.zip
sudo ./sessionmanager-bundle/install -i /usr/local/sessionmanagerplugin -b /usr/local/bin/session-manager-plugin
```

## 📚 추가 정보

### Windows 버전과의 차이점

| 기능 | Windows (v5.1.9) | macOS (v5.2.0) |
|------|------------------|----------------|
| 터미널 | Windows Terminal (wt.exe) + WSL | iTerm2 / Terminal.app |
| RDP 클라이언트 | mstsc.exe | Windows App / Microsoft Remote Desktop |
| 경로 처리 | WSL 경로 변환 (`D:\` → `/mnt/d/`) | pathlib 정규화 |
| DB 도구 | HeidiSQL | DBeaver (자동 연결) |

### AWS IAM 권한 요구사항

EC2 인스턴스가 S3 파일 전송을 사용하려면 다음 권한 필요:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::ec2menu-file-transfer-*",
        "arn:aws:s3:::ec2menu-file-transfer-*/*"
      ]
    }
  ]
}
```

## 🔗 관련 링크

- [AWS CLI 설치](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [AWS SSM Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
- [iTerm2](https://iterm2.com/)
- [FreeRDP](https://www.freerdp.com/)
- [Homebrew](https://brew.sh/)

## 📝 버전 히스토리

### v5.2.0 (2025-12-17) - macOS 버전
- 🍎 macOS 네이티브 지원
- 🖥️ iTerm2/Terminal.app 통합
- 🔌 FreeRDP 클라이언트 지원
- 🗑️ WSL 관련 코드 제거

### v5.1.9 (Windows 버전)
- 🔍 SSM 명령 디버깅
- 🛠️ AWS CLI 설치 확인
- 📝 전송 과정 로그 출력

## 📄 라이센스

개인 및 사내 사용 목적으로 자유롭게 사용 가능합니다.

## 👤 작성자

jsj - DevOps Engineer

---

**참고**: 이 스크립트는 Windows 버전(`ec2menu_v5.1.9.py`)에서 macOS용으로 포팅되었습니다.
