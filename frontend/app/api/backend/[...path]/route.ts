import { NextRequest, NextResponse } from "next/server";

const ALLOWED_PATHS = new Set(["health", "ready", "symbols", "trades"]);
const BOOK_PATH = /^books\/(\d{6})$/;
const UPSTREAM_TIMEOUT_MS = 5_000;
const SHARD_CACHE_TTL_MS = 30_000;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

type ShardCache = {
  expiresAt: number;
  shards: Map<string, number>;
};

let shardCache: ShardCache | null = null;

function shardUrls(): string[] {
  const many = process.env.BACKEND_SHARD_URLS;
  if (many) {
    return many
      .split(",")
      .map((url) => url.trim())
      .filter(Boolean);
  }
  const one = process.env.BACKEND_BASE_URL;
  return one ? [one] : [];
}

async function loadShards(primaryUrl: string): Promise<Map<string, number>> {
  if (shardCache && shardCache.expiresAt > Date.now()) {
    return shardCache.shards;
  }
  const target = new URL("/api/v1/symbols/", primaryUrl);
  target.searchParams.set("limit", "100");
  const response = await fetch(target, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error("symbol list is unavailable");
  }
  const payload = (await response.json()) as {
    results?: Array<{ ticker?: string; simulation_enabled?: boolean; matcher_shard?: number | null }>;
  };
  const shards = new Map<string, number>();
  for (const item of payload.results ?? []) {
    if (!item.simulation_enabled || item.ticker == null || item.matcher_shard == null) {
      continue;
    }
    shards.set(item.ticker, item.matcher_shard);
  }
  shardCache = { expiresAt: Date.now() + SHARD_CACHE_TTL_MS, shards };
  return shards;
}

function tickerFromRequest(upstreamPath: string, request: NextRequest): string | null {
  const bookMatch = upstreamPath.match(BOOK_PATH);
  if (bookMatch) {
    return bookMatch[1];
  }
  if (upstreamPath === "trades") {
    return request.nextUrl.searchParams.get("symbol");
  }
  return null;
}

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const upstreamPath = path.join("/");
  if (!ALLOWED_PATHS.has(upstreamPath) && !BOOK_PATH.test(upstreamPath)) {
    return NextResponse.json({ detail: "backend route is not allowed" }, { status: 404 });
  }

  const urls = shardUrls();
  if (urls.length === 0) {
    return NextResponse.json({ detail: "BACKEND_BASE_URL is not configured" }, { status: 503 });
  }

  let backendBaseUrl = urls[0];
  const ticker = tickerFromRequest(upstreamPath, request);
  if (ticker && urls.length > 1) {
    try {
      const shards = await loadShards(urls[0]);
      const shard = shards.get(ticker);
      if (shard == null || shard < 0 || shard >= urls.length) {
        return NextResponse.json({ detail: "matcher shard is not configured" }, { status: 502 });
      }
      backendBaseUrl = urls[shard];
    } catch {
      return NextResponse.json(
        { detail: "backend is unavailable" },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
  }

  const target = new URL(`/api/v1/${upstreamPath}/`, backendBaseUrl);
  target.search = request.nextUrl.search;

  try {
    const upstream = await fetch(target, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "backend is unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
