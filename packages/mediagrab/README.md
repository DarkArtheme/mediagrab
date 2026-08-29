# mediagrab

A library that turns a social-media URL into downloaded media plus its text description.

Providers implement `Provider.resolve(url) -> MediaPost`. First provider: Instagram
(Reels → video, `/p/` posts → photo/mixed carousels). TikTok is planned.

Part of the reels-downloader monorepo; see the repository root README for setup.
