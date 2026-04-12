# Korean Aggressive Opening Momentum — 자동매매 시스템

> 국내 주식(코스피/코스닥) 장초반 데이트레이딩 자동매매 시스템

## 개요

한국투자증권 Open API를 사용하는 장초반 모멘텀 데이트레이딩 자동매매 시스템입니다.
5분 Opening Range Breakout (ORB) 전략을 핵심으로, AI 보조 분석(Gemini 2.5 Flash Lite)을
활용하되 최종 의사결정은 규칙 기반 엔진이 담당합니다.

### 핵심 철학

- **안전 최우선**: 16개 불변 안전 레일, AI 우회 불가
- **AI는 보조자**: 분석만 제공, 최종 결정권 없음
- **치명적 손실 방지**: 일일/종목당 손실 한도, 자동 HALTED 전환
- **paper 먼저**: 기본 모의투자 모드, 실전 전환은 이중 플래그 필요

## 빠른 시작

### 1. 환경 설정

```bash
cd autotrader
cp .env.example .env
# .env 파일에서 실제 값 입력:
# - KIS_PAPER_APP_KEY, KIS_PAPER_APP_SECRET, KIS_PAPER_ACCOUNT_NO
# - DATABASE_URL (Supabase 또는 PostgreSQL)
# - GEMINI_API_KEY
```

### 2. Python 백엔드 실행

```bash
cd autotrader
pip install -e .    # 또는 uv pip install -e .
python -m uvicorn backend.main:app --reload --port 8000
```

### 3. React 대시보드 실행 (개발 모드)

```bash
cd autotrader/frontend
npm install
npm run dev         # http://localhost:3002
```

### 4. Docker 실행

```bash
cd autotrader
docker build -t autotrader .
docker run -p 8000:8000 --env-file .env autotrader
```

## 프로젝트 구조

```
autotrader/
├── backend/                  # Python 백엔드
│   ├── main.py              # FastAPI 진입점
│   ├── config/              # 설정
│   ├── strategy/            # 전략 엔진 (상태기계, 진입/청산 규칙)
│   ├── brokers/kis/         # 한투 API 어댑터
│   ├── execution/           # 주문 관리
│   ├── risk/                # 리스크 엔진 (안전 레일)
│   ├── ai/                  # AI 보조 분석 (Gemini)
│   ├── persistence/         # DB (SQLAlchemy + PostgreSQL)
│   ├── monitoring/          # 로깅
│   └── tests/               # pytest 테스트
├── frontend/                # Next.js 대시보드
│   └── app/page.tsx         # 메인 대시보드
├── Dockerfile               # 통합 빌드
├── render.yaml              # Render 배포
├── pyproject.toml           # Python 의존성
└── .env.example             # 환경변수 템플릿
```

## 안전 레일 (16개 불변 규칙)

| # | 규칙 | 위반 시 동작 |
|---|------|-------------|
| 1 | 일일 최대 손실 한도 (-3%) | 당일 거래 완전 중지 |
| 2 | 종목당 최대 손실 한도 | 즉시 청산 + 진입 금지 |
| 3 | 최대 동시 보유 2종목 | 신규 진입 거부 |
| 4 | 종목당 재진입 2회 | 재진입 거부 |
| 5 | 손절 후 5분 쿨다운 | 재진입 대기 |
| 6 | VI 발동 시 2분 차단 | 진입 거부 |
| 7 | 15:10 이후 진입 금지 | 진입 거부 |
| 8 | API 오류 5회 누적 | 시스템 HALTED |
| 9 | 실전 주문 이중 플래그 | 미설정 시 차단 |
| 10 | 긴급 거래 정지 | 전체 주문 차단 |
| 11 | 서버 재시작 복구 | 포지션 상태 복원 |
| 12 | 미체결 60초 타임아웃 | 자동 취소 |
| 13 | 중복 주문 방지 | 멱등성 키로 차단 |
| 14 | paper/live 분리 | 모드 혼용 불가 |
| 15 | 실전 함수 보호장치 | 조건 미충족 시 예외 |
| 16 | AI 안전 레일 우회 불가 | AI 응답 무시 |

## 실전 투자 전환 체크리스트

> ⚠️ 반드시 아래 모든 항목을 확인한 후 실전 전환하세요.

1. [ ] 모의투자로 최소 2주 이상 안정적 운용 확인
2. [ ] 일일 손실 한도, 종목당 손실 한도 적절히 설정
3. [ ] KIS 실전용 앱키/시크릿 발급 및 설정
4. [ ] 실전용 계좌번호 설정
5. [ ] `TRADING_MODE=live` 설정
6. [ ] `LIVE_TRADING=true` 설정
7. [ ] `CONFIRM_LIVE_ORDERS=true` 설정
8. [ ] 긴급 정지 버튼 동작 확인
9. [ ] 프로덕션 PostgreSQL DB 마이그레이션 완료
10. [ ] API 키 주기적 재발급 스케줄 확인

## 위험 포인트 10가지

1. **네트워크 장애**: API 호출 실패 시 HALTED 전환, 기존 포지션은 수동 관리 필요
2. **토큰 만료**: 24시간 유효, 자동 갱신 실패 시 재발급 필요
3. **VI 발동**: 변동성 완화장치 발동 시 주문 불가, 기존 포지션 영향
4. **슬리피지**: 시장가 주문 시 체결가가 예상과 다를 수 있음
5. **Supabase 제한**: Free 플랜 연결 제한 (15 connections), 실전에서는 매니지드 DB 사용
6. **API Rate Limit**: 초당 호출 제한, 모의투자가 더 낮음
7. **장 시작 집중**: 09:00~09:05 집중 시간대에 API 지연 가능
8. **Render 콜드 스타트**: Free/Starter 플랜에서 슬립 후 첫 요청 지연
9. **데이터 정합성**: DB 장애 시 포지션/주문 불일치 위험
10. **AI 할루시네이션**: Gemini 응답이 JSON 스키마를 벗어나면 무효 처리

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy(async) |
| Frontend | Next.js 15, React 19, Tailwind CSS 4 |
| Database | PostgreSQL (asyncpg), Supabase 호환 |
| AI | Gemini 2.5 Flash Lite |
| Deploy | Docker, Render |
| Testing | pytest, pytest-asyncio |
| Broker | 한국투자증권 Open API v2 |
