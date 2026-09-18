type ReadyTopology = {
  shard_index?: number;
  shard_count?: number;
  listen_port?: number;
};

export function resolveMatcherShardUrls(
  configured: string[],
  ready: ReadyTopology,
): string[] {
  const seeds = configured.map((url) => url.replace(/\/$/, "")).filter(Boolean);
  const shardCount = ready.shard_count;
  const shardIndex = ready.shard_index;
  const listenPort = ready.listen_port;
  if (
    seeds.length === 0 ||
    shardCount == null ||
    shardIndex == null ||
    listenPort == null ||
    shardCount < 1 ||
    shardIndex < 0 ||
    shardIndex >= shardCount ||
    listenPort < 1
  ) {
    throw new Error("ready payload is missing shard topology");
  }
  if (seeds.length === shardCount) {
    return seeds;
  }
  const hosts = new Set(seeds.map((url) => new URL(url).hostname));
  if (hosts.size > 1) {
    throw new Error(
      `configured ${seeds.length} shard URLs but matcher reports ${shardCount} shards`,
    );
  }
  const seed = new URL(seeds[0]);
  const basePort = listenPort - shardIndex;
  if (basePort < 1) {
    throw new Error("listen_port is inconsistent with shard_index");
  }
  return Array.from({ length: shardCount }, (_, index) => {
    const next = new URL(seed.href);
    next.port = String(basePort + index);
    next.pathname = next.pathname.replace(/\/$/, "");
    return next.origin + (next.pathname === "/" ? "" : next.pathname);
  });
}
