import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  experimental: {
    useTypeScriptCli: false,
  },
};

export default nextConfig;
