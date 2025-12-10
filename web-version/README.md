# EC2Menu Web Version

AWS 리소스 관리를 위한 웹 애플리케이션 버전

## 프로젝트 구조

```
web-version/
├── backend/                 # FastAPI 백엔드
│   ├── main.py             # 메인 API 서버
│   ├── aws_manager.py      # 기존 AWS 관리 클래스 import
│   ├── websocket_terminal.py # WebSocket 터미널 관리
│   ├── models.py           # Pydantic 모델들
│   └── requirements.txt    # Python 의존성
├── frontend/               # React 프론트엔드
│   ├── src/
│   │   ├── components/     # React 컴포넌트들
│   │   ├── pages/         # 페이지 컴포넌트들
│   │   ├── services/      # API 호출 서비스들
│   │   └── App.jsx        # 메인 앱
│   ├── package.json       # Node.js 의존성
│   └── vite.config.js     # Vite 설정
├── docker-compose.yml      # 전체 서비스 구성
└── README.md              # 이 파일
```

## 기능

- ✅ EC2 인스턴스 관리 및 SSM 터미널 접속
- ✅ RDS 데이터베이스 연결 및 웹 SQL 클라이언트
- ✅ ECS 컨테이너 관리 및 접속
- ✅ ElastiCache 클러스터 연결
- ✅ S3 경유 파일 전송
- ✅ 실시간 배치 작업 관리
- ✅ 연결 히스토리 및 캐싱

## 개발 진행

### Phase 1: 기본 구조 설정 ✅
- [x] 프로젝트 폴더 생성
- [ ] 백엔드 API 구조 생성
- [ ] 프론트엔드 React 앱 생성

### Phase 2: 기존 코드 통합
- [ ] AWSManager 클래스 import 및 API 래핑
- [ ] 파일 전송 기능 웹 적용
- [ ] 캐싱 시스템 연동

### Phase 3: 웹 터미널 구현
- [ ] SSM WebSocket 터미널
- [ ] xterm.js 통합

### Phase 4: 고급 기능
- [ ] 웹 RDP 클라이언트
- [ ] 웹 SQL 클라이언트
- [ ] 실시간 상태 모니터링

## 🚀 빠른 시작 (Docker 전용)

### 필수 요구사항
- Docker Desktop 설치 및 실행
- AWS 자격증명 설정 (~/.aws/credentials 또는 환경변수)

### 실행 방법

**Windows:**
```bash
start.bat
```

**Linux/Mac:**
```bash
./start.sh
```

**수동 실행:**
```bash
# 전체 서비스 시작
docker-compose up -d --build

# 브라우저에서 접속
# http://localhost:8080
```

### 접속 정보
- **웹 앱**: http://localhost:8080
- **백엔드 API**: http://localhost:8000  
- **API 문서**: http://localhost:8000/docs

### 서비스 관리
```bash
# 서비스 중지
docker-compose down

# 로그 확인
docker-compose logs -f

# 서비스 상태 확인
docker-compose ps
```