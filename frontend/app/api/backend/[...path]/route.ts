import { NextRequest, NextResponse } from "next/server";

const ALLOWED_PATHS = new Set(["health", "ready", "symbols", "trades"]);
const BOOK_PATH = /^books\/(\d{6})$/;
const UPSTREAM_TIMEOUT_MS = 5_000;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function backendBaseUrl(): string {
  return (process.env.BACKEND_BASE_URL ?? "").replace(/\/$/, "");
}

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const upstreamPath = path.join("/");
  if (!ALLOWED_PATHS.has(upstreamPath) && !BOOK_PATH.test(upstreamPath)) {
    return NextResponse.json({ detail: "backend route is not allowed" }, { status: 404 });
  }

  const baseUrl = backendBaseUrl();
  if (!baseUrl) {
    return NextResponse.json({ detail: "BACKEND_BASE_URL is not configured" }, { status: 503 });
  }

  const target = new URL(`/api/v1/${upstreamPath}/`, baseUrl);
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
    return new NextResponse(JSON.stringify({ detail: "backend is unavailable" }), {
      status: 502,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  }
}
