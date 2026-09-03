import { NextRequest, NextResponse } from "next/server";

const ALLOWED_PATHS = new Set(["health", "ready", "symbols", "books/005930", "trades"]);
const UPSTREAM_TIMEOUT_MS = 5_000;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const upstreamPath = path.join("/");
  if (!ALLOWED_PATHS.has(upstreamPath)) {
    return NextResponse.json({ detail: "backend route is not allowed" }, { status: 404 });
  }

  const backendBaseUrl = process.env.BACKEND_BASE_URL;
  if (!backendBaseUrl) {
    return NextResponse.json({ detail: "BACKEND_BASE_URL is not configured" }, { status: 503 });
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
