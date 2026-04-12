# ============================================================
# Korean Aggressive Opening Momentum - Docker Build
# ============================================================
# Multi-stage build:
#   Stage 1: Next.js 빌드 (React 대시보드)
#   Stage 2: Python 백엔드 + React 정적파일 통합
# ============================================================

# ---- Stage 1: Next.js 빌드 ----
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --production=false
COPY frontend/ .
RUN npm run build

# ---- Stage 2: Python 백엔드 ----
FROM python:3.12-slim AS production

# 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리
WORKDIR /app

# Python 의존성 설치
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# 백엔드 소스 복사
COPY backend/ ./backend/
COPY alembic.ini ./

# Next.js 빌드 산출물 복사
COPY --from=frontend-build /app/frontend/out ./frontend/out/

# 환경변수 기본값 (실제 값은 Render 대시보드에서 설정)
ENV PORT=8000
ENV HOST=0.0.0.0
ENV TRADING_MODE=paper
ENV LIVE_TRADING=false
ENV CONFIRM_LIVE_ORDERS=false

# 포트 노출
EXPOSE ${PORT}

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# 실행
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
