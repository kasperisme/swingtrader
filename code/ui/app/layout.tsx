import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Suspense } from "react";
import Script from "next/script";
import "./globals.css";
import { Analytics } from "@vercel/analytics/next";
import {
  SiteFooter,
  SITE_X_PROFILE_URL,
  SITE_INSTAGRAM_PROFILE_URL,
} from "@/components/site-footer";
import { SiteHeader, SiteHeaderFallback } from "@/components/site-header";
import { CavemanModeProvider } from "@/lib/caveman-mode";
import { AnalyticsProvider } from "@/lib/analytics/AnalyticsProvider";
import { Pixels } from "@/components/pixels";

// Always anchor metadataBase to the canonical production URL. Vercel preview
// deployments set VERCEL_URL to a hashed `*.vercel.app` host — using that as
// metadataBase leaks the preview URL into every OG/Twitter card and breaks
// social-share previews for the production site.
const canonicalSite =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.newsimpactscreener.com";
const previewSite = process.env.VERCEL_URL
  ? `https://${process.env.VERCEL_URL}`
  : "http://localhost:3000";
const metadataBase = new URL(
  process.env.VERCEL_ENV === "production" || !process.env.VERCEL_URL
    ? canonicalSite
    : previewSite,
);

const SITE_TITLE_PRIMARY =
  "News Impact Screener — Catch market-moving news before the crowd";
const SITE_DESCRIPTION =
  "News Impact Screener maps every breaking story to the tickers and sectors it touches — within minutes, not hours. Built for retail investors who want signal, not noise.";

export const metadata: Metadata = {
  metadataBase,
  title: {
    default: SITE_TITLE_PRIMARY,
    template: "%s · News Impact Screener",
  },
  description: SITE_DESCRIPTION,
  applicationName: "News Impact Screener",
  authors: [{ name: "News Impact Screener" }],
  alternates: { canonical: "/" },
  twitter: {
    card: "summary_large_image",
    site: "@newsimpactscrnr",
    creator: "@newsimpactscrnr",
    title: SITE_TITLE_PRIMARY,
    description: SITE_DESCRIPTION,
  },
  openGraph: {
    type: "website",
    url: "/",
    siteName: "News Impact Screener",
    title: SITE_TITLE_PRIMARY,
    description: SITE_DESCRIPTION,
  },
  other: {
    "social:x": SITE_X_PROFILE_URL,
    "social:twitter": SITE_X_PROFILE_URL,
    "social:instagram": SITE_INSTAGRAM_PROFILE_URL,
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
      <head>
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-FQ87KHKLS5"
          strategy="afterInteractive"
        />
        <Script id="gtag-init" strategy="afterInteractive">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', 'G-FQ87KHKLS5');
          `}
        </Script>
        <Pixels />
      </head>
      <body className={`${jakartaSans.className} antialiased`}>
        <Analytics />
        <AnalyticsProvider />
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
          disableTransitionOnChange
        >
          <Suspense
            fallback={
              <>
                <SiteHeaderFallback />
              </>
            }
          >
            <CavemanModeProvider>
              <Suspense fallback={<SiteHeaderFallback />}>
                <SiteHeader />
              </Suspense>
              {children}
              <SiteFooter />
            </CavemanModeProvider>
          </Suspense>
        </ThemeProvider>
      </body>
    </html>
  );
}
