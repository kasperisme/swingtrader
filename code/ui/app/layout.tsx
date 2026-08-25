import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Suspense } from "react";
import Script from "next/script";
import "./globals.css";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import {
  SiteFooter,
  SITE_X_PROFILE_URL,
  SITE_INSTAGRAM_PROFILE_URL,
} from "@/components/site-footer";
import { SiteHeader, SiteHeaderFallback } from "@/components/site-header";
import { CavemanModeProvider } from "@/lib/caveman-mode";
import { AnalyticsProvider } from "@/lib/analytics/AnalyticsProvider";
import { Pixels } from "@/components/pixels";
import {
  METADATA_BASE,
  SITE_URL,
  SITE_NAME,
  SITE_SAME_AS,
  AUTHOR,
} from "@/lib/site";


const SITE_TITLE_PRIMARY =
  "News Impact Screener — Catch market-moving news before the crowd";
const SITE_DESCRIPTION =
  "News Impact Screener maps every breaking story to the tickers and sectors it touches — within minutes, not hours. Built for retail investors who want signal, not noise.";

export const metadata: Metadata = {
  metadataBase: METADATA_BASE,
  title: {
    default: SITE_TITLE_PRIMARY,
    template: "%s · News Impact Screener",
  },
  description: SITE_DESCRIPTION,
  applicationName: "News Impact Screener",
  authors: [{ name: "News Impact Screener" }],
  twitter: {
    card: "summary_large_image",
    site: "@newsimpactscrnr",
    creator: "@newsimpactscrnr",
    title: SITE_TITLE_PRIMARY,
    description: SITE_DESCRIPTION,
  },
  // NOTE: no `alternates.canonical` and no `openGraph.url` here on purpose.
  // Both are INHERITED by every child segment that doesn't set its own, so a
  // root-level "/" made /articles, /blog, /blog/*, /docs, /docs/* and /pricing
  // all declare the homepage as their canonical — which is why they read
  // "Crawled – currently not indexed" in Search Console. Each route sets its
  // own; see `alternates: { canonical: … }` in the individual pages.
  openGraph: {
    type: "website",
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

/**
 * Site-wide entity graph. The site had no Organization markup at all, so
 * nothing tied the domain to a real publisher or to the social profiles that
 * carry the same brand — the `sameAs` set is what lets a search engine treat
 * them as one entity rather than three unrelated accounts. `founder` points at
 * the same Person node the About page and every article byline use.
 */
const siteJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": `${SITE_URL}/#organization`,
      name: SITE_NAME,
      alternateName: "NewsImpactScreener",
      url: SITE_URL,
      logo: {
        "@type": "ImageObject",
        url: `${SITE_URL}/icon.png`,
      },
      sameAs: SITE_SAME_AS,
      founder: { "@id": `${SITE_URL}/#author` },
      knowsAbout: [
        "stock market news",
        "swing trading",
        "equity research",
        "news sentiment analysis",
      ],
    },
    {
      "@type": "Person",
      "@id": `${SITE_URL}/#author`,
      name: AUTHOR.name,
      jobTitle: AUTHOR.role,
      url: AUTHOR.url,
      worksFor: { "@id": `${SITE_URL}/#organization` },
    },
    {
      "@type": "WebSite",
      "@id": `${SITE_URL}/#website`,
      url: SITE_URL,
      name: SITE_NAME,
      publisher: { "@id": `${SITE_URL}/#organization` },
    },
  ],
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
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(siteJsonLd) }}
        />
        <Analytics />
        <SpeedInsights />
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
