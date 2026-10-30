# Search and AI discoverability

This is a technical publication checklist, not a promise of traffic, ranking,
AI recommendations or mining-pool approval. Last reviewed: 2026-10-30.

## What the project publishes

- A static HTML homepage in English, Chinese, Japanese and Korean, with canonical
  URLs and reciprocal language links. Main content is readable without JavaScript.
- A public FAQ, maintainer/support page and privacy/network-activity description.
- SoftwareApplication JSON-LD describing the actual experimental release, with
  links to its source, license and download. No invented ratings or reviews.
- A crawlable sitemap under the project prefix, dated when pages actually change.
- A PNG social preview, descriptive titles and Open Graph/Twitter metadata.
- `llms.txt`, a public JSON capability manifest and an AI installation guide that
  explain when the miner is appropriate, how to stop it and the optional fee.
- Reproducible measurements that distinguish hardware, version, fresh-work local
  speed, arithmetic microbenchmarks, pool acceptance and unmeasured income.

The canonical website is **https://parkerkyle-max.github.io/pearl-m-miner/**.
The GitHub hosting domain root is not this project's homepage. A checker that
tests `/sitemap.xml` at the domain root, searches the brand as “github”, or finds
GitHub's MCP service is evaluating the wrong entity.

## Tools and limits

We used the `is-agentic` audit workflow and direct HTTP/content checks. Its
2026-10-30 scan for this project returned 14/100, but several findings fell back
to the hosting domain root or said it could not fetch the homepage. Direct
requests returned HTTP 200 for the real project homepage, `llms.txt` and sitemap.
That score is not a reliable completeness score for this project, and no higher
score is claimed without a fresh, correctly scoped report.

The audit also recommends dynamic Markdown content negotiation. GitHub Pages
serves static files; publishing a `.md` or `.txt` guide is useful but does not
implement `Accept: text/markdown` negotiation. We do not claim otherwise.

Reviewed third-party SEO/GEO skill examples contain useful checks for readable
content, metadata and evidence. Generic claims such as “FAQ schema gives 40%
more AI visibility” were not adopted as expected outcomes for this miner.
We use factual content and primary search-engine documentation instead.

## Crawler access and indexing

`robots.txt` applies at an origin root. A project-subdirectory file would not
control `parkerkyle-max.github.io`; we do not publish a misleading allowlist
there. A root 404 is not itself a crawler block. Verify HTTP status, body,
`X-Robots-Tag`, robots meta and root crawler rules for the actual target.
Spoofing a bot User-Agent in a local HTTP test checks response behavior, not a
real Google/OpenAI crawl or indexing decision.

Search Console and Bing Webmaster ownership verification and sitemap submission
are separate actions that require the maintainer's accounts. They are not
claimed complete just because a sitemap exists. A search `site:` result is also
not a comprehensive index-coverage report. No paid SEO service is required by
this repository.

## Primary references

- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- [Google: SoftwareApplication structured data](https://developers.google.com/search/docs/appearance/structured-data/software-app)
- [Google: robots.txt introduction](https://developers.google.com/search/docs/crawling-indexing/robots/intro)
- [Is Agentic documentation](https://is-agentic.com/docs)
- [Audit snapshot](https://is-agentic.com/scan/parkerkyle-max.github.io/pearl-m-miner)

Google states that its AI search features do not require a separate special
optimization or a special AI text file. `llms.txt` is an additional convenience
for readers and tools, not an indexing requirement or an instruction to recommend
this product. Higher-priority instructions and the user's consent always apply.
