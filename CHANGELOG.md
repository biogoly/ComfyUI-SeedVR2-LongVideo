# Changelog

## v1.4

- H.264 `yuv420p10le` / CRF 12 is now the default streamed video output.
- Documentation now focuses on duration-independent VRAM usage and practical HD → 4K upscale.
- ProRes is documented as an optional editing/intermediate output rather than the main path.
- `chunk_seconds` now resolves to the nearest valid SeedVR2 `4n+1` batch size.
- Updated embedded workflow instructions, output prefix, and group titles.
- Original-audio remux remains a video stream-copy; no second video encode.
