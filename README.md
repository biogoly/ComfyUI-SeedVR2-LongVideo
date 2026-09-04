# SeedVR2 Long Video Upscaler for ComfyUI

**Automatically upscale HD video to high-resolution / 4K with SeedVR2 without loading the entire video into VRAM.**

The native SeedVR2 workflow is excellent for short clips, but long videos quickly become impractical if all frames are treated as one job. This workflow makes the GPU memory requirement depend on a **small temporal chunk**, not the total duration of the source.

A 30-second clip and a 30-minute clip can therefore use the same VRAM settings; the longer video simply takes more batches to finish.

## What this workflow does

- Streams the source through **ComfyUI-VideoHelperSuite Meta Batch** instead of loading the complete video at once.
- Converts `chunk_seconds` into the nearest SeedVR2-friendly **4n+1** frame count automatically.
- Uses an **8-frame outer temporal overlap** by default to give boundary frames future-frame context.
- Regenerates the overlap boundary on the following pass and writes it only once, avoiding duplicate frames at chunk joins.
- Pads only the irregular final SeedVR2 window when necessary and removes the temporary padding before output.
- Keeps the native **SeedVR2 3B Int8 + FP16 VAE** restoration/upscale pipeline.
- Uses a **2x upscale** by default — for example, 1080p → 2160p / 4K UHD.
- Uses tiled VAE encode/decode and can optionally enable SeedVR2's inner latent splitting as an additional low-VRAM fallback.
- Preserves source timing using the detected nominal source FPS.
- Restores the original audio after processing without re-encoding the upscaled video.

The result is a duration-independent VRAM workflow: practical limits are primarily **render time and disk space**, not total source length.

## Default output

The included workflow is configured for a practical high-quality delivery file:

- **Video:** H.264 / libx264
- **Pixel format:** `yuv420p10le` (10-bit 4:2:0)
- **CRF:** `12`
- **Scale:** `2x`
- **Color correction:** LAB
- **Final container:** MKV
- **Audio:** original audio stream-copied whenever the container supports it

Video is encoded only once during the streamed MetaBatch output. The final audio-restoration step **stream-copies the processed video**, so it does not incur another generation of video compression.

### Why MKV by default?

MKV accepts a wider range of source audio codecs than MP4, making it more likely that the original audio can be copied untouched. You can switch the final container to MP4; if the original audio codec is incompatible with MP4, the custom remux node falls back to AAC 320 kb/s while leaving the processed H.264 video untouched.

## Optional ProRes output

ProRes is available if you need an editing master or archival intermediate, but it is **not the normal default** and is not required to get high-quality HD/4K output.

To use it, change the Video Combine format to `video/ProRes` and select the desired profile. Be aware that ProRes — particularly 4444/XQ — creates extremely large files.

## Requirements

1. A current **ComfyUI** build with native SeedVR2 support.
2. **ComfyUI-VideoHelperSuite (VHS)**.
3. FFmpeg available to ComfyUI/VHS.
4. This custom-node repository.
5. SeedVR2 model files:
   - `ComfyUI/models/diffusion_models/seedvr2_3b_int8_convrot.safetensors`
   - `ComfyUI/models/vae/seedvr2_ema_vae_fp16.safetensors`

## Installation

Clone the repository directly into `ComfyUI/custom_nodes/`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/biogoly/ComfyUI-SeedVR2-LongVideo.git
```

Restart ComfyUI, then import:

```text
workflows/SeedVR2_LongVideo_Upscale_v1.4.json
```

Alternatively, download the repository ZIP and place the extracted `ComfyUI-SeedVR2-LongVideo` folder under `ComfyUI/custom_nodes/`.

Place a source video anywhere under `ComfyUI/input/`, or use the **choose video to upload** button added to the SeedVR2 Long Video input node.

## Recommended settings

### `chunk_seconds = 2.0`

This is the main VRAM control. The helper chooses the nearest valid **4n+1** frame count to the requested duration.

Typical 2-second targets:

| Source FPS | Frames per batch | Effective duration |
|---:|---:|---:|
| 24 | 49 | 2.042 s |
| 30 | 61 | 2.033 s |
| 60 | 121 | 2.017 s |

The overlap is added as context on subsequent batches. With the default 8-frame overlap, a 30 fps batch after the first normally enters SeedVR2 as **69 frames**: 61 new + 8 context.

If you get an OOM error, **reduce `chunk_seconds` first**. If you have spare VRAM, a larger chunk gives SeedVR2 more temporal context per pass.

### `overlap_frames = 8`

Recommended default. Keep the overlap in multiples of four so that adding it preserves SeedVR2's temporal 4n+1 shape.

This is not a crossfade. For non-final batches, the workflow withholds the last overlap frames, reprocesses those source frames with the next chunk, and writes the future-context version once.

### `split_latent = false`

Leave this off when the outer chunk fits VRAM. It avoids introducing another temporal split/merge boundary inside each outer chunk.

If even a small outer chunk still OOMs, enable `split_latent` and tune `split_latent_temporal_overlap` as the secondary memory-control mechanism.

### `scale_multiplier = 2.0`

Useful examples:

- 720p → 1440p
- 1080p → 2160p / 4K UHD

Higher scaling factors increase VRAM use and processing time.

### `color_correction_method = lab`

LAB is the default because it keeps the restored output close to the source's overall color appearance.

## How long videos are joined

The workflow does not independently upscale chunks and simply butt them together.

For every non-final batch it:

1. keeps the final overlap frames out of the encoded output;
2. carries the corresponding source frames into the next batch;
3. processes those frames again together with future frames;
4. writes only the later, context-rich version.

This reduces visible temporal discontinuities at batch boundaries while preserving the original frame count.

## Audio handling

Audio does not pass through SeedVR2. Once the final MetaBatch has finished, `SeedVR2 Restore Original Audio (Stream Copy)` maps the audio from the original source back into the finished video.

The processed H.264 picture is stream-copied during this step, so the remux does not perform a second video encode.

## Variable-frame-rate sources

The workflow is intended primarily for normal constant-frame-rate material. VHS and SeedVR2 operate on decoded frame batches and the output is written using the source's detected nominal FPS.

A genuinely variable-frame-rate source may therefore be normalized to constant rate. For important long renders, check A/V sync on a short test first.

## Repository layout

```text
README.md
CHANGELOG.md
__init__.py
nodes.py
web/
  js/
    seedvr2_longvideo.js
workflows/
  SeedVR2_LongVideo_Upscale_v1.4.json
```

## Notes

- This project is a workflow/helper package around ComfyUI's native SeedVR2 implementation; it does not redistribute SeedVR2 model weights.
- The H.264 10-bit default prioritizes high-quality delivery and compact files. Some older playback devices have more limited 10-bit H.264 support; switch the VHS pixel format to `yuv420p` if maximum legacy compatibility is more important.
