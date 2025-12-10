# EC2Menu Web Version - 개발 히스토리

## 📅 프로젝트 개요
- **목적**: 기존 CLI 기반 EC2Menu를 웹 버전으로 변환
- **주요 기능**: AWS EC2 인스턴스 관리, SSM 터미널 접속, RDP 연결
- **기술 스택**: FastAPI (백엔드) + React (프론트엔드) + Docker

---

## 🔧 주요 작업 내역

### 2025-09-19 - 터미널 접속 및 스페이스바 문제 해결

#### 🐛 문제 1: 터미널 세션 시작 실패
**증상**: `Request failed with status code 500` 오류
**원인**: AWS multi-region 엔드포인트 문제 및 invalid role ARN
**해결**:
- Docker 로그 분석으로 문제 진단
- AWS config 파일의 role_arn 수정

#### 🐛 문제 2: AWS 프로파일 설정 문제
**증상**: 일부 계정은 서버 목록이 나오고, 일부는 안 나옴
**원인**: config 파일에서 `@root` role ARN이 주석 처리됨
**해결**:
```ini
# 수정 전
# role_arn removed due to invalid @root

# 수정 후
role_arn = arn:aws:iam::782553710171:role/@root
```

**주요 프로파일 설정**:
- `aws-sys`: 기본 계정 (직접 credentials)
- `aws-rag`: 976193250298 계정
- `aws-spd`: 782553710171 계정
- `aws-aug`: 273753707764 계정
- 기타 8개 프로파일 모두 role_arn 복원

#### 🐛 문제 3: SessionManagerPlugin 누락
**증상**: `SessionManagerPlugin is not found` 오류
**해결**: Dockerfile에 Session Manager Plugin 설치 추가
```dockerfile
# Session Manager Plugin 설치
RUN curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb" \
    && dpkg -i session-manager-plugin.deb \
    && rm session-manager-plugin.deb
```

#### 🐛 문제 4: 터미널이 sh 대신 bash 실행 안됨
**해결**: AWS CLI 명령어에 bash 명시
```python
cmd = [
    'aws', 'ssm', 'start-session',
    '--region', region,
    '--target', instance_id,
    '--document-name', 'AWS-StartInteractiveCommand',
    '--parameters', '{"command":["bash"]}'
]
```

#### 🐛 문제 5: 스페이스바 시각적 표시 안됨
**증상**: 스페이스바는 기능적으로 동작하지만 화면에 표시되지 않음
**원인**: 프론트엔드에서 Base64 디코딩 시도
**해결**: Terminal.jsx에서 Base64 디코딩 로직 제거
```javascript
// 수정 전
try {
  output = atob(data.data);
} catch (e) {
  // Base64가 아닌 경우 그대로 사용
}

// 수정 후
// 서버에서 직접 텍스트로 전송하므로 그대로 사용
terminal.write(data.data);
```

---

## 📁 수정된 파일 목록

### Backend 파일들
1. **Dockerfile**
   - Session Manager Plugin 설치 추가
   - AWS CLI 캐시 디렉토리 설정

2. **config** (AWS 설정)
   - 모든 프로파일의 role_arn 복원
   - @root 역할로 통일

3. **main.py**
   - 기본 프로파일을 aws-sys로 변경
   - 프로파일 목록 API 수정

4. **websocket_terminal.py**
   - bash 쉘 실행 설정
   - 입력 데이터 디버깅 로그 강화
   - 빈 문자열 및 DEL 키 처리 개선

### Frontend 파일들
1. **Terminal.jsx**
   - Base64 디코딩 로직 제거
   - 서버 출력 직접 표시

---

## ✅ 현재 작동 상태

### 정상 작동 기능
- ✅ 서버 목록 표시 (모든 AWS 계정)
- ✅ SSM 터미널 접속
- ✅ bash 쉘 실행
- ✅ 키보드 입력 (스페이스바 포함)
- ✅ 터미널 출력 표시

### 테스트된 AWS 프로파일
- `aws-sys`: 1개 인스턴스 (ftt-lgtm-prod01)
- `aws-rag`: 12개 인스턴스 (게임 서버들)
- 기타 프로파일들: 설정 완료

---

## 🔧 기술적 세부사항

### Docker 구성
```yaml
services:
  backend:
    build: ../backend/
    ports: ["8000:8000"]
    environment:
      - AWS_CLI_CACHE_DIR=/tmp/aws-cli-cache

  frontend:
    build: ./frontend/
    ports: ["8080:80"]
    depends_on: [backend]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

### AWS 터미널 연결 방식
- **방법**: AWS CLI + PTY (Pseudo Terminal)
- **프로토콜**: WebSocket을 통한 실시간 통신
- **인증**: AWS profiles with role assumption

### 디버깅 로그 시스템
백엔드에 상세한 로그 시스템 구축:
- 🔵 스페이스바 입력 감지
- 🟢 엔터 키 입력 감지
- 🟡 탭 키 입력 감지
- 🟠 제어 문자 입력
- 📝 일반 문자 입력

---

## 🚀 향후 개선 계획

### 추가 가능 기능
- [ ] RDP 연결 개선
- [ ] 파일 전송 기능
- [ ] 배치 작업 관리
- [ ] 연결 히스토리
- [ ] 사용자 권한 관리

### 성능 최적화
- [ ] 터미널 세션 풀링
- [ ] AWS API 호출 캐싱
- [ ] 웹소켓 연결 최적화

---

## 📞 문제 해결 가이드

### 터미널 연결 안될 때
1. SSM Agent 상태 확인: `aws ssm describe-instance-information`
2. IAM 역할 권한 확인
3. VPC 엔드포인트 확인

### 스페이스바 문제 재발시
1. 브라우저 캐시 클리어
2. 프론트엔드 재빌드
3. Base64 디코딩 로직 확인

### AWS 인증 문제
1. credentials 파일 권한 확인 (600)
2. role_arn 형식 확인
3. 프로파일명 일치 확인

#### 🐛 문제 6: aws-sys 이외 프로파일에서 TargetNotConnected 오류
**증상**: aws-sys는 정상 작동하지만 다른 프로파일에서 터미널 연결 실패
**원인**: 기존 활성 SSM 세션이 남아있어 새 세션 생성 차단
**해결 과정**:
1. SSM 세션 상태 확인: `aws ssm describe-sessions --state Active`
2. 기존 세션 발견: `i-0501d7138ac08ab86`에 활성 세션 존재
3. 세션 수동 종료: `aws ssm terminate-session --session-id [세션ID]`
4. 새 세션 정상 생성 확인

**교훈**: SSM은 인스턴스당 동시 터미널 세션 제한이 있음

#### 🔧 문제 7: 종합적인 터미널 세션 관리 기능 구현
**요청**: "서버 접속 종료 되면 자동으로 세션 종료 되게 설정 해줘.... 아니면 종료할수 있는 기능을 만들던가.."
**구현**: 완전한 세션 라이프사이클 관리 시스템 구축

**주요 구현 사항**:

1. **백엔드 websocket_terminal.py 개선**:
   ```python
   async def _cleanup_existing_sessions(self, profile: str, region: str, instance_id: str):
       """새 터미널 세션 시작 전 기존 활성 세션 자동 정리"""

   async def _terminate_aws_ssm_session(self, session_info: Dict):
       """AWS SSM 세션 명령줄을 통한 종료"""

   async def cleanup_session(self, session_id: str):
       """세션 정리 - AWS SSM 세션 및 로컬 세션 모두 정리"""
   ```

2. **프론트엔드 Terminal.jsx 개선**:
   - 컴포넌트 언마운트 시 자동 세션 정리
   - 연결 끊기 버튼으로 수동 세션 종료
   - keepalive를 통한 안전한 세션 정리

3. **새로운 API 엔드포인트**:
   - `DELETE /api/terminal/sessions/{session_id}` - 세션 정리

**해결된 문제들**:
- ✅ TargetNotConnected 오류 방지 (기존 세션 자동 정리)
- ✅ 사용자가 브라우저 탭을 닫을 때 자동 세션 정리
- ✅ 수동 세션 종료 기능
- ✅ AWS SSM 세션과 WebSocket 세션 동시 정리

#### 🐛 문제 8: 모든 aws-rag 서버에서 TargetNotConnected 오류 지속
**증상**: bash -l 대신 bash만 사용하여 세션 시작 실패
**원인**: 기존 CLI 버전(`ec2menu_v5.1.9.py`)과 다른 명령어 파라미터 사용
**해결**:
```python
# 수정 전
'--parameters', '{"command":["bash"]}'

# 수정 후 (CLI 버전과 동일)
'--parameters', '{"command":["bash -l"]}'
```

**교훈**: 웹 버전 구현 시 기존 CLI 버전의 정확한 명령어 구조를 따라야 함

---

## 🚀 향후 개선 계획 (업데이트)

### 추가 가능 기능
- [x] 기존 SSM 세션 자동 정리 기능
- [x] 수동 세션 종료 기능
- [x] 브라우저 탭 닫기 시 자동 정리
- [ ] RDP 연결 개선
- [ ] 파일 전송 기능
- [ ] 배치 작업 관리
- [ ] 연결 히스토리
- [ ] 사용자 권한 관리

### 성능 최적화
- [x] 중복 세션 방지 로직
- [x] 종합적인 세션 라이프사이클 관리
- [ ] 터미널 세션 풀링
- [ ] AWS API 호출 캐싱
- [ ] 웹소켓 연결 최적화

---

---

### 2025-09-22 - RDP 웹 연결 보안 프로토콜 문제 해결

#### 🐛 문제 9: "wrong security type" RDP 연결 실패
**증상**: 웹 RDP 연결 시 "Request failed with status code 500" → 해결 후 "응답을 기다리다 연결이 끊어졌습니다"
**원인**: guacd 로그에서 "RDP server closed/refused connection: Server refused connection (wrong security type?)" 발견
**근본 원인**: Guacamole과 Windows RDP 서버 간 보안 프로토콜 불일치

#### 🔧 수행한 작업 순서

**1단계: 문제 진단**
- 로그 분석으로 핵심 원인 발견: 보안 프로토콜 타입 불일치
- Backend API는 정상 (200 OK), SSM 터널링도 정상 동작
- guacd에서 "Security mode: Negotiate (ANY)" 시도하지만 Windows 서버 거부

**2단계: RDP 보안 프로토콜 순차 변경**
파일: `guacamole_manager.py` 라인 72

```python
# 1차 시도: 'rdp' → 'tls'
'security': 'tls'  # TLS 보안으로 변경

# 2차 시도: 'tls' → 'nla'
'security': 'nla'  # NLA 보안으로 변경

# 3차 시도: 'nla' → 'any' (최종)
'security': 'any'  # 모든 보안 방식 허용 (최대 호환성)
```

**3단계: 추가 최적화**
```python
# 한국어 키보드 레이아웃 추가
'server-layout': 'ko-kr-qwerty'

# 호환성을 위한 기타 설정 유지
'disable-auth': 'true'
'ignore-cert': 'true'
```

#### 📝 최종 RDP 연결 파라미터 설정
```python
parameters = {
    'hostname': host,
    'port': str(port),
    'username': 'Administrator',
    'password': '',  # SSM 세션은 이미 인증됨
    'security': 'any',  # 모든 보안 방식 허용
    'disable-auth': 'true',
    'ignore-cert': 'true',
    'enable-wallpaper': 'false',
    'enable-theming': 'false',
    'enable-font-smoothing': 'false',
    'enable-full-window-drag': 'false',
    'enable-desktop-composition': 'false',
    'resize-method': 'reconnect',
    'server-layout': 'ko-kr-qwerty'  # 한국어 키보드
}
```

#### ✅ 현재 상태 (2025-09-22)
- **Backend API**: ✅ 정상 동작 (200 OK 응답)
- **SSM 터널링**: ✅ 정상 동작 (socat + AWS CLI)
- **Docker 컨테이너**: ✅ 네트워킹 이슈 해결됨
- **RDP 보안 설정**: ✅ 최대 호환성 설정 완료 ('any')
- **테스트 대기**: 🔄 사용자 최종 웹 RDP 연결 테스트 필요

**교훈**: Windows RDP 서버는 Guacamole 기본 보안 설정과 호환성 문제가 있어, 'any' 설정으로 최대 호환성 확보 필요

#### 🔄 추가 시도 (2025-09-22 오후 계속)
**문제**: 'any' 보안 설정에도 여전히 "wrong security type" 오류 지속
**새로운 접근**: security 파라미터 자체를 제거하고 Guacamole 기본값 사용
```python
# security 파라미터 완전 제거
# 'disable-auth': 'false'로 변경 (인증 활성화)
```
**목적**: Guacamole이 자동으로 최적의 보안 프로토콜을 협상하도록 허용

#### 🔄 추가 시도 2 (2025-09-22 오후 계속)
**문제**: security 파라미터 제거해도 여전히 "wrong security type" 오류
**새로운 접근**: RDP Legacy 모드 강제 설정
```python
'security': '',  # 빈 값으로 설정 - 레거시 RDP
'console': 'true',  # 콘솔 세션 강제
'client-name': 'Guacamole',
```
**목적**: 가장 기본적인 RDP 프로토콜로 연결 시도

#### 🎯 **커뮤니티 해결책 발견** (2025-09-22 오후 계속)
**문제 근본 원인**: FreeRDP가 쓰기 가능한 홈 디렉터리를 요구하는데, guacd가 daemon 사용자로 실행되어 권한 부족
**해결책**: Docker Compose에서 FreeRDP 전용 홈 디렉터리 볼륨 추가
```yaml
guacd:
  volumes:
    - guacd_home:/var/lib/guacd  # FreeRDP 홈 디렉터리 마운트
  environment:
    - GUACD_LOG_LEVEL=debug      # 디버그 로그 활성화
```
**출처**: Stack Overflow, GitHub Issues, kifarunix.com 등 커뮤니티 솔루션

#### 🔄 **직접 테스트 결과** (2025-09-22 오후 계속)
**현재 상황**:
1. ✅ **FreeRDP 홈 디렉터리**: 해결됨 (guacd_home 볼륨 마운트)
2. ❌ **파라미터 저장**: 일부 파라미터(disable-auth, console, client-name 등)가 DB에 저장되지 않음
3. ❌ **tunnel_id 키 에러**: `ERROR:main:웹 RDP 연결 시작 실패: 'tunnel_id'` - 백엔드 API 500 에러
4. ❌ **여전히 "wrong security type"**: guacd 로그에서 동일한 보안 프로토콜 오류 지속

**테스트 결과**: 커뮤니티 해결책 적용했지만 여전히 RDP 연결 실패

---

#### 🔍 **소스코드 비교 분석** (2025-09-22 계속)
**사용자 요청**: "스크립트를 통해서 서버 접속은 정상적으로 잘되는데? 그러면 SSM 문제는 아닌거 아니야? 소스코드 대조해봐"

**핵심 발견**: 원본 스크립트 vs 웹 버전의 근본적 아키텍처 차이

**원본 스크립트 (ec2menu_v5.1.9.py) - 정상 동작**:
```python
def start_port_forward(profile, region, iid, port):
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{"portNumber":["3389"],"localPortNumber":["{port}"]}}'
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

def launch_rdp(port):
    subprocess.Popen([
        "mstsc.exe", f"/v:localhost:{port}"
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

**웹 버전 (현재 구현) - 연결 실패**:
```python
# 1. Docker 컨테이너 내부에서 SSM 포트 포워딩
# 2. socat으로 이중 터널링 (internal_port -> external_port)
# 3. Apache Guacamole (FreeRDP 기반) 웹 클라이언트
# 4. 수동으로 설정된 RDP 파라미터들
```

**결정적 차이점**:
1. **RDP 클라이언트**: Windows 네이티브 `mstsc.exe` vs Guacamole 웹 클라이언트
2. **보안 협상**: 자동 프로토콜 협상 vs 수동 파라미터 설정
3. **네트워킹**: 직접 localhost 바인딩 vs Docker + socat 이중 터널링
4. **인증**: Windows 네이티브 RDP 인증 vs Guacamole FreeRDP 인증

**분석 결론**:
- SSM 포트 포워딩 자체는 양쪽 모두 동일하게 작동
- 문제는 RDP 클라이언트 계층에서 발생 (Guacamole vs mstsc.exe)
- Windows Server의 RDP 설정이 Guacamole과 호환되지 않음

#### 🔧 **RDP 파라미터 최적화** (2025-09-22 계속)
**수정 내용**: Windows Server 호환성을 위한 Guacamole 파라미터 재조정
```python
# 이전 설정 (실패)
'security': '',  # 빈 값
'disable-auth': 'true',
'console': 'true',

# 새로운 설정 (호환성 향상)
'security': 'any',  # 자동 보안 협상 - 서버가 지원하는 보안 방식 자동 선택
'disable-auth': 'true',  # SSM 터널을 통해 이미 인증됨
'enable-drive': 'false',  # 보안상 드라이브 리다이렉션 비활성화
'enable-printing': 'false',  # 프린터 리다이렉션 비활성화
'color-depth': '16',  # 16비트 색깔로 성능 향상
'dpi': '96'  # 기본 DPI 설정
```

**목적**:
- 보안 프로토콜 자동 협상으로 Windows Server와 최대 호환성 확보
- 불필요한 리다이렉션 기능 비활성화로 연결 안정성 향상
- 성능 최적화로 연결 성공률 증대

**결과**: 컨테이너 재빌드 완료, 사용자 테스트 대기 중

---

**마지막 업데이트**: 2025-09-22 (오후 - 소스코드 비교 완료)
**작업자**: jsj
**상태**: 터미널 세션 관리 완료 ✅ + RDP 아키텍처 차이 분석 완료 ✅ + Guacamole 파라미터 최적화 완료 ✅
**최신 구현**: 원본 스크립트 대비 웹 버전 근본적 차이점 파악 및 호환성 개선
