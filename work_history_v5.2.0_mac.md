# EC2Menu v5.2.0 macOS 버전 작업 기록

## 프로젝트 정보

- **프로젝트**: AWS EC2/RDS/ElastiCache/ECS 접속 자동화 스크립트 (macOS 전용)
- **기반 버전**: ec2menu v5.1.9 (Windows/WSL)
- **현재 버전**: ec2menu v5.2.0 (macOS)
- **작업 기간**: 2025년 12월

## 버전 히스토리

### v5.2.0 (2025-12-18) - macOS 네이티브 버전

**주요 변경사항:**

- macOS 네이티브 지원 (iTerm2/Terminal.app 통합)
- WSL 관련 코드 완전 제거
- Windows RDP 클라이언트 지원 (Microsoft Remote Desktop)
- pathlib 기반 경로 정규화
- 배치 작업 재시도 로직 강화

## 2025-12-18 작업 내역

### 세션 1: 코드 품질 개선 (P1, P2, P3 개선사항)

#### 작업 내용

**1. P1-8: Python 3.9 호환성 개선**
- `from __future__ import annotations` 추가
- 이전 Python 버전 타입 힌팅 호환성 확보

**2. P3-19: Import 문 재정리 (PEP 8 준수)**

```python
# 표준 라이브러리
import argparse
import atexit
...

# 서드파티 라이브러리
import boto3
from botocore.exceptions import ClientError
```

**3. P1-4: Thread Safety 개선**

```python
_temp_files_to_cleanup: list[Path] = []
_temp_files_lock = threading.Lock()  # 추가

with _temp_files_lock:
    _temp_files_to_cleanup.append(rdp_file)
```

**4. P1-1: 세션 유효성 검사 추가**

```python
def cleanup_temp_bucket(self):
    # 세션 유효성 검사 (프로그램 종료 시 세션이 무효화될 수 있음)
    if not hasattr(self, 'aws_manager') or not self.aws_manager:
        logging.warning(f"AWS Manager가 유효하지 않아 임시 S3 버킷 삭제를 건너뜁니다")
        return
```

**5. P1-6: DB 비밀번호 마스킹 (보안)**

```python
# 변경 전
print(f"비밀번호: {db_password}")

# 변경 후
print(f"비밀번호: {'*' * 8}")  # 보안: 비밀번호 마스킹
```

**6. P1-2, P1-5, P2-9~P2-18: Task 에이전트를 통한 일괄 적용**
- Config 클래스 패턴 적용
- 매직 넘버 제거
- 코드 중복 제거 (DRY 원칙)
- 에러 핸들링 개선

#### 커밋 내역
```bash
# 1차 커밋
git commit -m "refactor: P1 보안 및 안정성 개선 (1차)"

# 2차 커밋
git commit -m "security: DB 비밀번호 마스킹 처리 (P1-6)"

# 3차 커밋
git commit -m "refactor: P1 + P2 안정성 및 품질 개선 완료"
```

### 세션 2: 배치 작업 재시도 로직 강화

#### 문제 상황

**사용자 테스트 결과:**

```text
총 11개 인스턴스 테스트:
- 성공: 7개
- 실패: 4개 (rag-auth01, rag-gmt11, rag-lobby11, rag-lobby13)
- 실패 원인: 0.5초 타임아웃 (간헐적 네트워크 문제)
```

**사용자 요구사항:**

> "기본모드가 좋은거같아 다만 연결에 문제가 생겼을시 재시도 횟수를 늘리거나 연결시도를 계속 하거나 하는게 있어야 할거같다"

#### 해결 과정

**Phase 1: 재시도 설정 추가**

```python
# Config 클래스에 추가
BATCH_COMMAND_RETRY = 5  # 2 → 5
BATCH_RETRY_DELAY = 3     # 신규
```
- 재시도 횟수 증가
- Exponential backoff: 3s, 6s, 9s, 12s, 15s

**결과:** 사용자 피드백 "이거 재시도를 너무 빨리하는건가... 너무 순식간에 끝나고 실패율은 비슷해.."

**Phase 2: 대기 시간 증가 + 수동 재시도 옵션**

```python
BATCH_RETRY_DELAY = 10          # 3초 → 10초
BATCH_COMMAND_RETRY = 3         # 5회 → 3회 (대신 긴 대기)
BATCH_RETRY_MAX_DELAY = 60      # 최대 60초

# 실패 인스턴스 재시도 프롬프트 추가
if failed_count > 0:
    retry_choice = input("실패한 인스턴스만 다시 시도하시겠습니까? (y/N): ")
    if retry_choice == 'y':
        retry_results = self.execute_batch_command(failed_instances, command)
```

**결과:** 수동 재시도는 성공했지만, 사용자가 관찰: "그냥 내가볼때 그냥 재시도를 안하는거 같은데..."

**Phase 3: 재시도 로직 완전 재작성 (근본 해결)**

**문제 원인 발견:**

- 기존 재시도 로직은 `send_command()` 실패만 처리
- 실제 타임아웃은 `get_command_invocation()` 대기 중 발생
- 0.5초 타임아웃 = 명령 전송 자체 실패인데 재시도 안됨

**해결 방법:**

```python
def execute_on_instance(instance_data, retry_count=0):
    max_retries = Config.BATCH_COMMAND_RETRY  # 3

    # 전체 실행을 재시도 루프로 감싸기
    for attempt in range(max_retries + 1):
        if attempt > 0:
            # 재시도 대기 with 사용자 피드백
            delay = min(Config.BATCH_RETRY_DELAY * attempt, Config.BATCH_RETRY_MAX_DELAY)
            print(colored_text(
                f"🔄 {instance_name} 재시도 {attempt}/{max_retries} (대기: {delay}초)",
                Colors.WARNING
            ))
            print(colored_text(
                f"   💡 SSM Agent 복구 또는 네트워크 안정화 대기 중...",
                Colors.INFO
            ))
            time.sleep(delay)

        try:
            # 1. 명령 전송
            response = ssm.send_command(...)
            command_id = response['Command']['CommandId']

            # 2. 결과 대기 (전체 폴링 루프)
            while waited < max_wait:
                status = get_command_invocation(...)

                if status == 'Success':
                    if attempt > 0:
                        print(f"✅ {instance_name} 재시도 성공!")
                    return BatchJobResult(status='SUCCESS', ...)

                elif status in ['Failed', 'Cancelled', 'TimedOut']:
                    if attempt < max_retries:
                        # 재시도 트리거
                        raise Exception(f"Command {status}")
                    else:
                        return BatchJobResult(status='FAILED', ...)

            # 타임아웃 발생
            if attempt < max_retries:
                print(f"⚠️  {instance_name}: 타임아웃 - 재시도 예정")
                continue  # 다음 재시도
            else:
                return BatchJobResult(status='TIMEOUT', ...)

        except ClientError as e:
            # send_command 실패 처리
            if attempt < max_retries:
                print(f"⚠️  {instance_name}: {error_code} - 재시도 예정")
                continue
            else:
                return BatchJobResult(status='FAILED', ...)
```

**핵심 변경:**

- 명령 전송 + 결과 대기 + 응답 파싱을 **전체** 재시도 루프로 감쌈
- 모든 실패 시나리오에서 재시도 트리거
- 재시도 진행 상황 실시간 표시 (🔄 이모지)
- 10초, 20초, 30초 점진적 대기로 SSM Agent 복구 시간 확보

#### 커밋 내역

```bash
# 1차 시도
git commit -m "feat: 배치 작업 재시도 로직 강화

- BATCH_COMMAND_RETRY: 2 → 5회
- BATCH_RETRY_DELAY: 3초 추가
- Exponential backoff 적용 (3s, 6s, 9s, 12s, 15s)"

# 2차 시도
git commit -m "feat: 배치 작업 재시도 전략 개선 및 실패 인스턴스 재시도 옵션 추가

- BATCH_RETRY_DELAY: 3초 → 10초
- BATCH_COMMAND_RETRY: 5회 → 3회
- 최대 대기 시간: 60초
- 실패 인스턴스 선택적 재시도 기능 추가"

# 최종 해결
git commit -m "fix: 배치 작업 재시도 로직 완전 수정

문제:
- 재시도 로직이 send_command 실패에만 적용됨
- 실제 타임아웃은 결과 대기 중 발생하는데 재시도 안됨
- 0.5초 타임아웃 발생 시 재시도 메시지 없이 즉시 실패

해결:
- execute_on_instance 함수 완전 재작성
- 전체 실행 과정(명령 전송 + 결과 대기 + 응답 파싱)을 재시도 루프로 감싸기
- 모든 실패 시나리오에서 재시도 트리거
- 재시도 진행 상황 실시간 표시 (🔄 메시지)
- 10초, 20초, 30초 점진적 대기로 SSM Agent 복구 시간 확보

재시도 트리거:
- send_command 실패
- get_command_invocation 타임아웃
- 명령 실행 실패 (Failed, Cancelled, TimedOut)"
```

#### 테스트 결과

**사용자 피드백:**

> "좋아 잘된다."
> "좋아 정상동작하네..."

- 재시도 메시지 정상 표시
- 실패율 개선
- SSM Agent 복구 시간 확보

## 기술적 개선사항 요약

### 1. 코드 품질

- Python 3.9+ 호환성 (`from __future__ import annotations`)
- PEP 8 Import 순서 준수
- Thread-safe 코드 (threading.Lock)
- 세션 유효성 검사
- DB 비밀번호 마스킹

### 2. 배치 작업 안정성

- 전체 실행 과정 재시도 (send + wait + parse)
- 점진적 대기 시간 (10s → 20s → 30s)
- 실패 인스턴스 선택적 재시도
- 실시간 진행 상황 표시

### 3. 사용자 경험

- 명확한 재시도 메시지 (🔄 이모지)
- SSM Agent 복구 안내 (💡 이모지)
- 수동 재시도 옵션
- 최종 결과 요약

## 최종 설정값

```python
class Config:
    # 배치 작업 설정
    BATCH_MAX_RETRIES = 3              # SSM 명령 전송 재시도 횟수
    BATCH_COMMAND_RETRY = 3            # 명령 실행 실패 시 재시도 횟수
    BATCH_RETRY_DELAY = 10             # 재시도 간 기본 대기 시간 (초)
    BATCH_RETRY_MAX_DELAY = 60         # 최대 대기 시간 (초)
    BATCH_TIMEOUT_SECONDS = 600        # 10분
    BATCH_MAX_WAIT_ATTEMPTS = 200
    BATCH_CONCURRENT_JOBS = 5          # 동시 실행 수 (기본 모드)
```

**재시도 전략:**

- 1차 실패 → 10초 대기 → 재시도
- 2차 실패 → 20초 대기 → 재시도
- 3차 실패 → 30초 대기 → 재시도
- 4차 실패 → 최종 실패 처리

## 향후 개선 제안

### Priority 1 (Quick Wins)

1. **즐겨찾기 기능** (2-3시간)
   - 자주 접속하는 인스턴스 북마크
   - 'f' 키로 추가/제거
   - `~/.ec2menu_bookmarks.json` 저장

2. **배치 결과 내보내기** (1-2시간)
   - CSV/JSON 포맷 지원
   - 보고서 자동 생성

3. **태그 기반 필터링** (3-4시간)
   - `Environment=production` 필터
   - 여러 필터 조합 (AND 조건)

4. **인스턴스 검색** (2-3시간)
   - `/keyword` 명령
   - Fuzzy search 지원

5. **실시간 모니터링 대시보드** (4-6시간)
   - CloudWatch 메트릭 조회
   - CPU/메모리/디스크 사용률 표시
   - 임계값 초과 시 색깔 경고

### Priority 2 (High Value)

- 인스턴스 시작/중지/재부팅 기능
- RDS 스냅샷 관리
- Lambda 함수 관리
- 비용 정보 표시
- MFA 기반 민감 작업 승인

### Priority 3 (Nice-to-Have)

- S3 버킷 브라우저
- Slack/Email 알림
- 통합 대시보드 (TUI)
- 플레이북 시스템

**추천 시작점:** 즐겨찾기 기능 (구현 간단, 즉시 효과)

## 참고 문서

- [README_mac.md](README_mac.md) - macOS 버전 사용 가이드
- [dev_ec2menu_v4.41_to_v5.1.9.md](dev_ec2menu_v4.41_to_v5.1.9.md) - Windows 버전 개발 히스토리
- [CLAUDE.md](CLAUDE.md) - Claude Code 작업 가이드

---

## 관련 리소스

### AWS 문서

- [SSM Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
- [SSM Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/execute-remote-commands.html)
- [ECS Exec](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html)

### macOS 통합

- [iTerm2](https://iterm2.com/)
- [AppleScript 가이드](https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/)

---

**작성자:** jsj
**최종 업데이트:** 2025-12-18
**버전:** v5.2.0
