import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Market Lab | Simulation Dashboard",
  description: "Private dashboard for the stock-market simulation environment",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
