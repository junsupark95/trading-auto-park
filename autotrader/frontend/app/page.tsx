'use client';

import { useEffect, useState, useCallback } from 'react';

// ========== Types ==========
interface HealthData {
  status: string;
  mode: string;
  live_trading: boolean;
  confirm_live_orders: boolean;
  emergency_stop: boolean;
  timestamp: string;
}

interface StrategyData {
  strategy_name: string;
  mode: string;
  state: string;
  is_live: boolean;
  can_execute_live_orders: boolean;
}

interface PnlData {
  daily_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_trades: number;
  win_rate: number;
}

interface AccountData {
  total_equity: number;
  available_cash: number;
}

interface RiskData {
  daily_loss_limit_pct: number;
  per_symbol_loss_limit_pct: number;
  emergency_stop: {
    is_active: boolean;
    activated_at: string | null;
    reason: string;
  };
}

interface AIData {
  enabled: boolean;
  model: string;
  daily_calls: number;
  daily_limit: number;
  available: boolean;
}

// ========== API Hook ==========
const API_BASE = typeof window !== 'undefined' && window.location.port === '3002'
  ? 'http://localhost:8000'
  : '';

async function fetchApi<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function postApi<T>(path: string, body: object): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ========== Dashboard ==========
export default function Dashboard() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [strategy, setStrategy] = useState<StrategyData | null>(null);
  const [pnl, setPnl] = useState<PnlData | null>(null);
  const [account, setAccount] = useState<AccountData | null>(null);
  const [risk, setRisk] = useState<RiskData | null>(null);
  const [ai, setAi] = useState<AIData | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState('');

  const refreshData = useCallback(async () => {
    const [h, s, p, acc, r, a] = await Promise.all([
      fetchApi<HealthData>('/api/health'),
      fetchApi<StrategyData>('/api/strategy/status'),
      fetchApi<PnlData>('/api/pnl'),
      fetchApi<AccountData>('/api/account'),
      fetchApi<RiskData>('/api/risk/status'),
      fetchApi<AIData>('/api/ai/status'),
    ]);
    if (h) { setHealth(h); setConnected(true); }
    else { setConnected(false); }
    if (s) setStrategy(s);
    if (p) setPnl(p);
    if (acc) setAccount(acc);
    if (r) setRisk(r);
    if (a) setAi(a);
    setLastUpdate(new Date().toLocaleTimeString('ko-KR'));
  }, []);

  useEffect(() => {
    refreshData();
    const interval = setInterval(refreshData, 5000);
    return () => clearInterval(interval);
  }, [refreshData]);

  const handleEmergencyStop = async () => {
    if (health?.emergency_stop) {
      await postApi('/api/emergency/resume', { reason: '대시보드에서 수동 해제' });
    } else {
      if (confirm('⚠️ 긴급 거래 정지를 활성화하시겠습니까?\n모든 신규 주문이 차단됩니다.')) {
        await postApi('/api/emergency/stop', { reason: '대시보드에서 수동 정지' });
      }
    }
    await refreshData();
  };

  const isPaper = health?.mode === 'paper';
  const isEmergency = health?.emergency_stop ?? false;

  return (
    <div className="min-h-screen p-4 md:p-6 lg:p-8">
      {/* Header */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8 animate-slide-up">
        <div>
          <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">
            <span className="bg-gradient-to-r from-purple-400 via-blue-400 to-green-400 bg-clip-text text-transparent">
              AutoTrader
            </span>
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Korean Aggressive Opening Momentum
          </p>
        </div>
        <div className="flex items-center gap-4">
          <span className={isPaper ? 'mode-paper' : 'mode-live'}>
            {isPaper ? '📋 PAPER' : '🔴 LIVE'}
          </span>
          <div className="flex items-center gap-2">
            <span className={`status-dot ${connected ? 'healthy' : 'unhealthy'}`} />
            <span className="text-xs text-[var(--text-secondary)]">
              {connected ? '연결됨' : '연결 끊김'}
            </span>
          </div>
          <span className="text-xs text-[var(--text-secondary)]">{lastUpdate}</span>
        </div>
      </header>

      {/* Emergency Stop Banner */}
      {isEmergency && (
        <div className="mb-6 p-4 rounded-xl bg-red-900/40 border border-red-500/50 animate-slide-up">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🚨</span>
            <div>
              <h3 className="font-bold text-red-300">긴급 거래 정지 활성화</h3>
              <p className="text-sm text-red-400">
                모든 신규 주문이 차단되었습니다. {risk?.emergency_stop?.reason}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Grid Layout */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {/* Strategy State */}
        <div className="glass-card animate-slide-up" style={{ animationDelay: '0.1s' }}>
          <div className="flex justify-between items-start mb-3">
            <h3 className="text-sm font-semibold text-[var(--text-secondary)]">전략 상태</h3>
            <span className="text-lg">🎯</span>
          </div>
          <p className="text-2xl font-bold">{strategy?.state ?? '---'}</p>
          <p className="text-xs text-[var(--text-secondary)] mt-1">
            {strategy?.strategy_name?.slice(0, 20)}
          </p>
        </div>

        {/* Account Balance */}
        <div className="glass-card animate-slide-up" style={{ animationDelay: '0.15s' }}>
          <div className="flex justify-between items-start mb-3">
            <h3 className="text-sm font-semibold text-[var(--text-secondary)]">현재 잔고 (예수금)</h3>
            <span className="text-lg">💳</span>
          </div>
          <p className="text-2xl font-bold text-white">
            {(account?.total_equity ?? 0).toLocaleString('ko-KR')}원
          </p>
          <p className="text-xs text-[var(--text-secondary)] mt-1">
            매수 가능액: {(account?.available_cash ?? 0).toLocaleString('ko-KR')}원
          </p>
        </div>

        {/* Daily PnL */}
        <div className="glass-card animate-slide-up" style={{ animationDelay: '0.2s' }}>
          <div className="flex justify-between items-start mb-3">
            <h3 className="text-sm font-semibold text-[var(--text-secondary)]">일일 손익</h3>
            <span className="text-lg">💰</span>
          </div>
          <p className={`text-2xl font-bold ${(pnl?.daily_pnl ?? 0) >= 0 ? 'glow-green' : 'glow-red'}`}>
            {(pnl?.daily_pnl ?? 0) >= 0 ? '+' : ''}{(pnl?.daily_pnl ?? 0).toLocaleString('ko-KR')}원
          </p>
          <div className="flex justify-between text-xs text-[var(--text-secondary)] mt-1">
            <span>실현: {(pnl?.realized_pnl ?? 0).toLocaleString('ko-KR')}원</span>
            <span>{pnl?.total_trades ?? 0}전 승률 {(pnl?.win_rate ?? 0).toFixed(1)}%</span>
          </div>
        </div>

        {/* Connection */}
        <div className="glass-card animate-slide-up" style={{ animationDelay: '0.25s' }}>
          <div className="flex justify-between items-start mb-3">
            <h3 className="text-sm font-semibold text-[var(--text-secondary)]">시스템</h3>
            <span className="text-lg">🔌</span>
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-xs">
              <span>API</span>
              <span className={`status-dot ${connected ? 'healthy' : 'unhealthy'}`} />
            </div>
            <div className="flex justify-between text-xs">
              <span>WebSocket</span>
              <span className="status-dot degraded" />
            </div>
            <div className="flex justify-between text-xs">
              <span>AI</span>
              <span className={`status-dot ${ai?.available ? 'healthy' : 'degraded'}`} />
            </div>
          </div>
        </div>
      </div>

      {/* Second Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {/* Positions */}
        <div className="glass-card lg:col-span-2 animate-slide-up" style={{ animationDelay: '0.3s' }}>
          <h3 className="text-sm font-semibold text-[var(--text-secondary)] mb-4">
            📈 보유 포지션
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[var(--text-secondary)] border-b border-[var(--border)]">
                  <th className="text-left py-2">종목</th>
                  <th className="text-right py-2">수량</th>
                  <th className="text-right py-2">평균가</th>
                  <th className="text-right py-2">현재가</th>
                  <th className="text-right py-2">손익</th>
                  <th className="text-right py-2">상태</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={6} className="text-center py-8 text-[var(--text-secondary)]">
                    보유 포지션 없음
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Risk Status */}
        <div className="glass-card animate-slide-up" style={{ animationDelay: '0.35s' }}>
          <h3 className="text-sm font-semibold text-[var(--text-secondary)] mb-4">
            🛡️ 리스크 상태
          </h3>
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-xs text-[var(--text-secondary)]">일일 손실 한도</span>
              <span className="text-xs font-mono glow-yellow">
                -{risk?.daily_loss_limit_pct ?? 3.0}%
              </span>
            </div>
            <div className="w-full bg-[var(--bg-secondary)] rounded-full h-2">
              <div className="bg-gradient-to-r from-green-500 to-green-400 h-2 rounded-full" style={{ width: '10%' }} />
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-[var(--text-secondary)]">종목당 손실 한도</span>
              <span className="text-xs font-mono glow-yellow">
                -{risk?.per_symbol_loss_limit_pct ?? 1.5}%
              </span>
            </div>
            <div className="w-full bg-[var(--bg-secondary)] rounded-full h-2">
              <div className="bg-gradient-to-r from-green-500 to-green-400 h-2 rounded-full" style={{ width: '5%' }} />
            </div>
            <div className="flex justify-between items-center mt-4">
              <span className="text-xs text-[var(--text-secondary)]">AI 호출</span>
              <span className="text-xs font-mono">
                {ai?.daily_calls ?? 0} / {ai?.daily_limit ?? 500}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-[var(--text-secondary)]">AI 모델</span>
              <span className="text-xs font-mono text-purple-400">
                {ai?.model ?? 'N/A'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Third Row: Emergency Stop + Watchlist */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Watchlist */}
        <div className="glass-card lg:col-span-2 animate-slide-up" style={{ animationDelay: '0.4s' }}>
          <h3 className="text-sm font-semibold text-[var(--text-secondary)] mb-4">
            👀 워치리스트
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[var(--text-secondary)] border-b border-[var(--border)]">
                  <th className="text-left py-2">종목</th>
                  <th className="text-right py-2">갭 (%)</th>
                  <th className="text-right py-2">거래량 비율</th>
                  <th className="text-right py-2">점수</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={4} className="text-center py-8 text-[var(--text-secondary)]">
                    스캔 대기 중
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Emergency Stop */}
        <div className="glass-card animate-slide-up flex flex-col items-center justify-center" style={{ animationDelay: '0.45s' }}>
          <h3 className="text-sm font-semibold text-[var(--text-secondary)] mb-6">
            ⚠️ 긴급 정지
          </h3>
          <button
            id="emergency-stop-button"
            className={`emergency-btn ${isEmergency ? 'active' : ''}`}
            onClick={handleEmergencyStop}
          >
            {isEmergency ? '✅ 거래 재개' : '🛑 긴급 정지'}
          </button>
          <p className="text-xs text-[var(--text-secondary)] mt-4 text-center max-w-[200px]">
            {isEmergency
              ? '거래 재개 시 모든 안전 레일이 리셋됩니다'
              : '모든 신규 주문을 즉시 차단합니다'}
          </p>
        </div>
      </div>

      {/* Footer */}
      <footer className="mt-8 text-center text-xs text-[var(--text-secondary)] opacity-60">
        <p>Korean Aggressive Opening Momentum v0.1.0</p>
        <p className="mt-1">⚠️ This is {isPaper ? 'PAPER TRADING' : 'LIVE TRADING'} mode</p>
      </footer>
    </div>
  );
}
