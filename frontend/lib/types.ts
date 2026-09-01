export type SymbolItem = {
  ticker: string;
  name: string;
  market: string;
  close_price: number;
  volume: number;
  trading_value: number;
  trading_value_rank: number;
  simulation_enabled: boolean;
};

export type SymbolResponse = {
  trade_date: string | null;
  results: SymbolItem[];
};

export type BookLevel = {
  price: number;
  qty: number;
};

export type BookResponse = {
  symbol: string;
  bids: BookLevel[];
  asks: BookLevel[];
};

export type Trade = {
  trade_id: string;
  symbol: string;
  executed_at: string;
  price: number;
  qty: number;
  buy_order_id: string;
  sell_order_id: string;
};

export type TradeResponse = {
  symbol: string;
  trades: Trade[];
};

export type HealthResponse = {
  status: string;
  database?: string;
};
