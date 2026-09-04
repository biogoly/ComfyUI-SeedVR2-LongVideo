# SeedVR2 Long Video Upscaler — HD → 4K, OOM-Safe

## Short description

Automatic long-video SeedVR2 upscale workflow for ComfyUI. Streams the source in temporally overlapping batches so VRAM use depends on chunk size rather than total video duration. Designed for practical HD → 4K restoration/upscale without manually trimming and stitching clips.

## Description

This workflow turns ComfyUI's native SeedVR2 video upscale into an automatic long-video pipeline.

Instead of loading an entire video into GPU memory or manually changing trim offsets for every short clip, VideoHelperSuite Meta Batch advances through the source until EOF. A custom overlap helper carries boundary frames into the next batch so they are regenerated with future-frame context and written only once.

### Highlights

- Arbitrarily long source videos from a VRAM perspective — memory use is controlled by the temporal chunk, not total duration
- Automatic 4n+1 SeedVR2 batch sizing from a simple `chunk_seconds` control
- 8-frame contextual overlap by default
- No duplicate frames at chunk boundaries
- 2x upscale default: 1080p → 2160p / 4K UHD
- H.264 `yuv420p10le`, CRF 12 default output
- Original audio restored after processing
- No second video encode during final audio remux
- Optional inner latent splitting for additional VRAM savings
- Optional ProRes output for editing/intermediate use

### Default settings

- Chunk duration: 2.0 s
- Outer overlap: 8 frames
- Scale: 2x
- Split latent: off
- Color correction: LAB
- Codec: H.264
- Pixel format: yuv420p10le
- CRF: 12
- Final container: MKV

### Requirements

- Current ComfyUI with native SeedVR2 support
- ComfyUI-VideoHelperSuite
- FFmpeg
- `seedvr2_3b_int8_convrot.safetensors`
- `seedvr2_ema_vae_fp16.safetensors`
- Included `ComfyUI-SeedVR2-LongVideo` helper nodes

### Installation

Copy the included `ComfyUI-SeedVR2-LongVideo` folder into `ComfyUI/custom_nodes/`, restart ComfyUI, then load `SeedVR2_LongVideo_Upscale_v1.4.json`.

### OOM tuning

If you run out of VRAM, lower `chunk_seconds` first. If even a short chunk is too large, enable `split_latent` as the secondary memory-control option.

### ProRes

ProRes is available as an optional output if you specifically need a high-bitrate editing/intermediate master. The normal workflow is intentionally configured for much more practical H.264 10-bit delivery.

## Suggested tags

ComfyUI, SeedVR2, Video Upscale, Video Restoration, 4K, Long Video, OOM, Video Workflow

## v1.4 notes

- Changed default output from ProRes 4444 XQ to H.264 `yuv420p10le`, CRF 12
- Reframed documentation around the core goal: long-video HD/4K upscale without duration-driven OOM
- ProRes moved to an optional editing-master workflow
- Corrected automatic batch sizing to use the nearest valid SeedVR2 4n+1 frame count
- Updated embedded workflow instructions and output naming
