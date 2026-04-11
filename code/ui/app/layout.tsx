import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Suspense } from "react";
import "./globals.css";
import { Analytics } from "@vercel/analytics/next";
import { SiteFooter, SITE_X_PROFILE_URL } from "@/components/site-footer";
import { SiteHeader, SiteHeaderFallback } from "@/components/site-header";

const defaultUrl = process.env.VERCEL_URL
  ? `https://${process.env.VERCEL_URL}`
  : "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(defaultUrl),
  title: "newsimpactscreener",
  description:
    "News Impact Screener connects headlines to stocks and sectors for retail investors—themes, exposure, and screening without terminal noise.",
  twitter: {
    card: "summary",
    site: "@newsimpactscrnr",
    creator: "@newsimpactscrnr",
  },
  openGraph: {
    type: "website",
    url: defaultUrl,
    title: "newsimpactscreener",
    description:
      "News Impact Screener connects headlines to stocks and sectors for retail investors—themes, exposure, and screening without terminal noise.",
  },
  other: {
    "social:x": SITE_X_PROFILE_URL,
    "social:twitter": SITE_X_PROFILE_URL,
  },
};

const jakartaSans = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  display: "swap",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${jakartaSans.className} antialiased`}>
        <Analytics />
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
          disableTransitionOnChange
        >
          <Suspense fallback={<SiteHeaderFallback />}>
            <SiteHeader />
          </Suspense>
          {children}
          <SiteFooter />
        </ThemeProvider>
      </body>
    </html>
  );
}
