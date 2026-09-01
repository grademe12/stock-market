"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  BookLevel,
  BookResponse,
  HealthResponse,
  SymbolItem,
  SymbolResponse,
  Trade,
  TradeResponse,
} from "@/lib/types";

const STATUS_INTERVAL_MS = 5_000;
const MARKET_INTERVAL_MS = 1_000;
const DEFAULT_SYMBOL: SymbolItem = {
  ticker: "005930",
  name: "삼성전자",
  market: "KOSPI",
  close_price: 0,
  volume: 0,
  trading_value: 0,
  trading_value_rank: 0,
  simulation_enabled: true,
};

type CheckState = "checking" | "online" | "offline";

type ServiceCheck = {
  state: CheckState;
  detail: string;
  latencyMs: number | null;
};

const INITIAL_CHECK: ServiceCheck = {
  state: "checking",
  detail: "확인 중",
  latencyMs: null,
};

class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

async function requestJson<T>(url: string): Promise<{ data: T; latencyMs: number }> {
  const startedAt = performance.now();
  const response = await fetch(url, { cache: "no-store" });
  const latencyMs = Math.round(performance.now() - startedAt);
  if (!response.ok) {
    throw new ApiError(response.status, `request failed (${response.status})`);
  }
  return { data: (await response.json()) as T, latencyMs };
}

function number(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function compactNumber(value: number) {
  return new Intl.NumberFormat("ko-KR", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function time(value: string | Date | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(typeof value === "string" ? new Date(value) : value);
}

export function Dashboard() {
  const [backend, setBackend] = useState<ServiceCheck>(INITIAL_CHECK);
  const [database, setDatabase] = useState<ServiceCheck>(INITIAL_CHECK);
  const [query, setQuery] = useState("");
  const [symbols, setSymbols] = useState<SymbolItem[]>([]);
  const [tradeDate, setTradeDate] = useState<string | null>(null);
  const [searchError, setSearchError] = useState("");
  const [selected, setSelected] = useState<SymbolItem>(DEFAULT_SYMBOL);
  const [book, setBook] = useState<BookResponse>({ symbol: "005930", bids: [], asks: [] });
  const [trades, setTrades] = useState<Trade[]>([]);
  const [marketError, setMarketError] = useState("");
  const [marketUpdatedAt, setMarketUpdatedAt] = useState<Date | null>(null);

  const refreshStatus = useCallback(async () => {
    const check = async (endpoint: "health" | "ready"): Promise<ServiceCheck> => {
      try {
        const { data, latencyMs } = await requestJson<HealthResponse>(
          `/api/backend/${endpoint}`,
        );
        const healthy = endpoint === "health" ? data.status === "ok" : data.status === "ready";
        return {
          state: healthy ? "online" : "offline",
          detail: endpoint === "ready" ? `database: ${data.database ?? "unknown"}` : data.status,
          latencyMs,
        };
      } catch (error) {
        return {
          state: "offline",
          detail: error instanceof ApiError ? error.message : "연결 실패",
          latencyMs: null,
        };
      }
    };

    const [backendResult, databaseResult] = await Promise.all([check("health"), check("ready")]);
    setBackend(backendResult);
    setDatabase(databaseResult);
  }, []);

  const refreshMarket = useCallback(async () => {
    if (!selected.simulation_enabled) return;
    try {
      const [{ data: bookData }, { data: tradeData }] = await Promise.all([
        requestJson<BookResponse>(`/api/backend/books/${selected.ticker}`),
        requestJson<TradeResponse>(
          `/api/backend/trades?symbol=${encodeURIComponent(selected.ticker)}&limit=50`,
        ),
      ]);
      setBook(bookData);
      setTrades(tradeData.trades);
      setMarketError("");
      setMarketUpdatedAt(new Date());
    } catch (error) {
      setMarketError(error instanceof ApiError ? error.message : "시장 데이터를 불러오지 못했습니다");
    }
  }, [selected]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refreshStatus(), 0);
    const interval = window.setInterval(() => void refreshStatus(), STATUS_INTERVAL_MS);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, [refreshStatus]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refreshMarket(), 0);
    const interval = window.setInterval(() => void refreshMarket(), MARKET_INTERVAL_MS);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, [refreshMarket]);

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      try {
        const { data } = await requestJson<SymbolResponse>(
          `/api/backend/symbols?q=${encodeURIComponent(query)}&limit=20`,
        );
        setSymbols(data.results);
        setTradeDate(data.trade_date);
        setSearchError("");
        const selectedUpdate = data.results.find((item) => item.ticker === selected.ticker);
        if (selectedUpdate) setSelected(selectedUpdate);
      } catch {
        setSearchError("종목 기준정보를 불러오지 못했습니다");
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, selected.ticker]);

  const overallState: CheckState = useMemo(() => {
    if (backend.state === "checking" || database.state === "checking") return "checking";
    return backend.state === "online" && database.state === "online" ? "online" : "offline";
  }, [backend.state, database.state]);

  const bestBid = book.bids[0]?.price ?? null;
  const bestAsk = book.asks[0]?.price ?? null;
  const spread = bestBid !== null && bestAsk !== null ? bestAsk - bestBid : null;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">ML</span>
          <div>
            <p>MARKET LAB</p>
            <span>SIMULATION CONTROL</span>
          </div>
        </div>
        <div className={`system-pill ${overallState}`}>
          <span className="status-dot" />
          {overallState === "online"
            ? "SYSTEM NOMINAL"
            : overallState === "checking"
              ? "CHECKING SYSTEM"
              : "SYSTEM DEGRADED"}
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">PRIVATE TAILNET · LIVE</p>
          <h1>시장 시뮬레이션<br />운영 대시보드</h1>
        </div>
        <div className="hero-meta">
          <span>ACTIVE MATCHER</span>
          <strong>1</strong>
          <p>단일 프로세스 메모리 호가창</p>
        </div>
      </section>

      <section className="status-grid" aria-label="서비스 상태">
        <StatusCard label="BACKEND" check={backend} index="01" />
        <StatusCard label="DATABASE" check={database} index="02" />
        <div className="status-card">
          <div className="status-card-head"><span>03</span><p>MARKET FEED</p></div>
          <strong>{marketError ? "STALE" : marketUpdatedAt ? "LIVE" : "WAIT"}</strong>
          <small>{marketError || `updated ${time(marketUpdatedAt)}`}</small>
        </div>
      </section>

      <section className="workspace">
        <aside className="symbol-panel panel">
          <div className="panel-heading">
            <div><span>REFERENCE</span><h2>종목 검색</h2></div>
            <small>{tradeDate ?? "NO DATA"}</small>
          </div>
          <label className="search-box">
            <span>⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="종목명 또는 코드"
              aria-label="종목 검색"
            />
          </label>
          {searchError ? <p className="inline-error">{searchError}</p> : null}
          <div className="symbol-list">
            {symbols.map((symbol) => (
              <button
                className={symbol.ticker === selected.ticker ? "symbol-row selected" : "symbol-row"}
                key={symbol.ticker}
                onClick={() => setSelected(symbol)}
                type="button"
              >
                <div>
                  <strong>{symbol.name}</strong>
                  <span>{symbol.ticker} · {symbol.market}</span>
                </div>
                <div className="symbol-price">
                  <strong>{number(symbol.close_price)}</strong>
                  <span>#{symbol.trading_value_rank}</span>
                </div>
              </button>
            ))}
            {!searchError && symbols.length === 0 ? (
              <p className="empty-copy">검색 결과가 없습니다.</p>
            ) : null}
          </div>
        </aside>

        <section className="market-panel panel">
          <div className="market-title">
            <div>
              <span className="ticker">{selected.ticker}</span>
              <h2>{selected.name}</h2>
              <p>{selected.market} · 기준 종가 {selected.close_price ? `${number(selected.close_price)}원` : "—"}</p>
            </div>
            <div className={selected.simulation_enabled ? "live-badge" : "live-badge disabled"}>
              {selected.simulation_enabled ? "SIMULATION LIVE" : "REFERENCE ONLY"}
            </div>
          </div>

          {selected.simulation_enabled ? (
            <>
              <div className="market-summary">
                <Metric label="BEST ASK" value={bestAsk ? number(bestAsk) : "—"} tone="ask" />
                <Metric label="SPREAD" value={spread !== null ? number(spread) : "—"} />
                <Metric label="BEST BID" value={bestBid ? number(bestBid) : "—"} tone="bid" />
              </div>
              <OrderBook asks={book.asks} bids={book.bids} />
            </>
          ) : (
            <div className="inactive-market">
              <span>NO ACTIVE MATCHER</span>
              <h3>이 종목은 현재 기준정보만 제공됩니다.</h3>
              <p>실시간 주문과 호가 매칭은 005930 종목에서만 실행 중입니다.</p>
            </div>
          )}
        </section>

        <aside className="trade-panel panel">
          <div className="panel-heading">
            <div><span>EXECUTIONS</span><h2>최근 체결</h2></div>
            <small>{trades.length} / 50</small>
          </div>
          <div className="trade-head"><span>시간</span><span>가격</span><span>수량</span></div>
          <div className="trade-list">
            {selected.simulation_enabled && trades.length > 0 ? trades.map((trade) => (
              <div className="trade-row" key={trade.trade_id}>
                <span>{time(trade.executed_at)}</span>
                <strong>{number(trade.price)}</strong>
                <span>{number(trade.qty)}</span>
              </div>
            )) : (
              <div className="empty-state"><span>∿</span><p>표시할 체결이 없습니다.</p><small>러너를 실행하면 체결이 여기에 나타납니다.</small></div>
            )}
          </div>
        </aside>
      </section>

      <footer>
        <span>STOCK-MARKET / DEV</span>
        <p>거래는 시뮬레이션이며 실제 주문을 전송하지 않습니다.</p>
        <span>{marketUpdatedAt ? `LAST SYNC ${time(marketUpdatedAt)}` : "AWAITING FEED"}</span>
      </footer>
    </main>
  );
}

function StatusCard({ label, check, index }: { label: string; check: ServiceCheck; index: string }) {
  return (
    <div className="status-card">
      <div className="status-card-head"><span>{index}</span><p>{label}</p></div>
      <strong className={check.state}>{check.state === "online" ? "ONLINE" : check.state === "checking" ? "CHECK" : "OFFLINE"}</strong>
      <small>{check.latencyMs !== null ? `${check.latencyMs} ms · ${check.detail}` : check.detail}</small>
    </div>
  );
}

function Metric({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return <div className={`metric ${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function OrderBook({ asks, bids }: { asks: BookLevel[]; bids: BookLevel[] }) {
  const visibleAsks = asks.slice(0, 8).reverse();
  const visibleBids = bids.slice(0, 8);
  const maxQuantity = Math.max(1, ...visibleAsks.map((level) => level.qty), ...visibleBids.map((level) => level.qty));

  return (
    <div className="orderbook">
      <div className="book-head"><span>구분</span><span>가격 (KRW)</span><span>잔량</span></div>
      <div className="book-side asks">
        {visibleAsks.length ? visibleAsks.map((level) => (
          <BookRow key={`ask-${level.price}`} level={level} side="ASK" maxQuantity={maxQuantity} />
        )) : <div className="book-empty">매도 대기 주문 없음</div>}
      </div>
      <div className="midline"><span>MARKET SPREAD</span></div>
      <div className="book-side bids">
        {visibleBids.length ? visibleBids.map((level) => (
          <BookRow key={`bid-${level.price}`} level={level} side="BID" maxQuantity={maxQuantity} />
        )) : <div className="book-empty">매수 대기 주문 없음</div>}
      </div>
    </div>
  );
}

function BookRow({ level, side, maxQuantity }: { level: BookLevel; side: "ASK" | "BID"; maxQuantity: number }) {
  return (
    <div className="book-row">
      <div className="depth" style={{ width: `${Math.max(4, (level.qty / maxQuantity) * 100)}%` }} />
      <span>{side}</span>
      <strong>{number(level.price)}</strong>
      <span>{compactNumber(level.qty)}</span>
    </div>
  );
}
