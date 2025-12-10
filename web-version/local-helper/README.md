# EC2Menu RDP Helper

웹 브라우저에서 RDP 연결을 자동으로 실행하는 로컬 헬퍼 프로그램입니다.

## 🚀 설치 방법

1. **관리자 권한으로 PowerShell 또는 명령 프롬프트 실행**
2. **설치 스크립트 실행**:
   ```batch
   install.bat
   ```

## 🖥️ 사용 방법

설치 후 웹 브라우저에서 RDP 버튼을 클릭하면:
1. `ec2rdp://localhost:3389` 같은 URL이 호출됨
2. 로컬 헬퍼 프로그램이 자동으로 실행됨
3. Windows RDP 클라이언트(`mstsc.exe`)가 열림

## 🔧 작동 원리

1. **URL 스키마**: `ec2rdp://` 프로토콜을 Windows에 등록
2. **헬퍼 프로그램**: Python 스크립트가 URL을 파싱하고 mstsc 실행
3. **자동 실행**: 브라우저에서 링크 클릭 시 자동으로 RDP 클라이언트 실행

## 📁 파일 구조

- `ec2rdp_helper.py` - 메인 헬퍼 프로그램
- `install.bat` - 설치 스크립트 (URL 스키마 등록)
- `uninstall.bat` - 제거 스크립트
- `README.md` - 이 파일

## 🗑️ 제거 방법

```batch
uninstall.bat
```

## 📋 요구사항

- **Python 3.7+** (시스템 PATH에 등록되어 있어야 함)
- **Windows 10/11**
- **관리자 권한** (설치 시에만 필요)

## 🔍 로그 파일

헬퍼 프로그램의 실행 로그는 다음 위치에 저장됩니다:
```
%USERPROFILE%\AppData\Local\EC2Menu\ec2rdp_helper.log
```

## 🧪 테스트

설치 후 다음 URL을 브라우저 주소창에 입력하여 테스트할 수 있습니다:
```
ec2rdp://localhost:3389
```

## ⚠️ 주의사항

- 방화벽이나 보안 소프트웨어에서 차단될 수 있습니다
- 처음 실행 시 브라우저에서 외부 프로그램 실행 확인을 요청할 수 있습니다
- Python이 시스템 PATH에 등록되어 있어야 합니다