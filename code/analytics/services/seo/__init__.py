"""seo — the post-deploy push half of search visibility.

`services.google_analytics` reads what Google already knows. This writes:
resubmits the sitemap to Search Console and pings IndexNow (Bing, Yandex,
Seznam, Naver) with changed URLs. Both exist because organic crawl rate on a
young domain is near zero — waiting to be re-crawled is the slow path.
"""
