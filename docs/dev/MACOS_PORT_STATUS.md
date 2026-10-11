# macOS port: changelog and to-do

Working notes for the macOS port on Apple Silicon (Rosetta, MoltenVK). The test title throughout is
LEGO Builder's Journey (PPSA05496, Unity HDRP). Known limits of each change are in
[TechnicalDebt.md](TechnicalDebt.md).

## Where it stands (2026-10-11)

- The title boots, plays audio, loads its first scene and draws it correctly apart from the two
  defects listed under "Rendering" below.
- About 4.9 frames per second on an M4 Pro, averaged over the main scene at 1080p. The rate swings
  between 3.4 and 6.5 inside one run.
- The first launch spends several minutes compiling large compute pipelines through Metal; later
  launches load them from the pipeline cache.
- Nothing is pushed. The work is three local commits on `macos-port`: `d21fdcca`, `82c4cc82`,
  `66005779`.

## Changelog

### 66005779: render Unity titles at 1080p

- The launcher rewrites `platform-ps5-video-out-width=3840` to `1920` in the bundle's copy of
  `Media/boot.config`. The title takes its render size from there, not from any `sceVideoOut` call.
  2.0 frames per second at 4K, about 4.9 on average at 1080p (the commit message's 6.6 was one stable
  stretch of a run). GPU time per frame went from 458 ms to 127 ms.
- `APS5_GPU_TIMES=<frames>` prints the draws and dispatches that cost the most, each timed between
  two device drains.

### 82c4cc82: software guest write watch

- macOS reported no write tracking, so the driver compared, re-uploaded and wrote back every
  texture at each use (92% of the driver thread). `GuestWriteWatch.cpp` now has a macOS backend that
  compares: every byte for a collect of up to 8 MiB against a kept copy, 32 bytes per 16 KiB page
  for larger ones. The driver takes the tracked path the other hosts use. 0.7 to 2 frames per second
  at 4K.
- Host memory imports are aligned to the hardware's 16 KiB pages for Metal.

### d21fdcca: boot a Unity HDRP title to its first scene

Kernel, loader and relinker:

- `sceKernelRaiseException` delivers on macOS as a host `SIGUSR1`, so Unity's garbage collector can
  stop threads. The Windows test `guest_raise_exception` runs on macOS too.
- `sceKernelLoadStartModule` passes `args`/`argp` to `module_start` and opens modules globally, so a
  later module binds an earlier one's exports (FMOD Studio needs FMOD's).
- The relinker converts every `.prx` outside the module directories where it is, without preloading
  it; the launcher stages those modules (Unity's `Media/Modules` and `Media/Plugins`).
- `sceKernelConvertLocaltimeToUtc` fills the 16-byte record the title's `mktime` reads.
- Launcher-built apps turn off the macOS "reopen windows" alert.

AGC driver and shader recompiler:

- Fetch shaders (binary type 8) register without preparation.
- `src_shared_base` and `src_private_base` decode; a compute shader the analysis rejects is deferred
  to its dispatch.
- Pixel shaders and rect-list pairs are prepared at the draw when the registered state differs.
- Stencil clear draws, depth-only draws without a pixel program, and a clamped viewport depth range
  for draws that do not use depth.
- Sampled image heap capacity 16 to 32; 8-bit sRGB formats in emulated comparison sampling.

## Tried and dropped

- **Page protection for write tracking.** Rosetta aborts with "unexpectedly need to EmulateForward"
  when a write fault lands inside some translated AVX stores. shadPS4 uses the same mechanism on
  macOS with no Rosetta workaround in its page manager; why it survives there is not understood.
- **Copy-on-write snapshots for write tracking.** macOS does report copied pages without signals,
  but it costs about 4 ms per 64 MiB, no better than comparing.
- **`APS5_SPIRV_OPT=full`.** No measurable gain; the largest shader stayed at 1,560,591 words.
- **`APS5_LABEL_FLUSH_US`.** Longer timers were slower; shorter ones cut GPU time but not the frame rate.
- **`MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS=0`.** No clear gain, and the device loss at scene change
  appeared in that run.
- **Write-watch tuning** (64 KiB samples, 1 MiB exact threshold). Collect time fell about seven times
  but the averaged frame rate did not improve.
- **Reporting a 1080p display from `sceVideoOutGetOutputStatus`.** The title ignores it.

## To do

Speed, in the order the measurements suggest:

1. Find out why the frame is cut into about 76 GPU submissions and 87 render passes, and merge
   consecutive draws to the same targets. Each pass is a full load and store on Apple's tile-based GPU.
2. The driver's queue-0 worker is near one full core: about a third is the write-watch collect, a
   third is MoltenVK encoding inside `vkQueueSubmit`. Cut the number of collects per frame rather than
   their cost.
3. Identify the heavy compute pass (shader `4c38002b9e78c48d`, 552,833 words, 25 ms for a 16x9
   dispatch) and why the recompiler's output for it is so large.
4. Check MoltenVK's fast-math setting; it was not looked at.

Stability:

5. Device loss at scene change (`kIOGPUCommandBufferCallbackErrorInvalidResource`), about one run in
   ten. Suspected cause, not confirmed: a Metal buffer over guest memory the title maps again. Wait
   for the GPU and drop the import before the remap.
6. Segfault in the title's exit handlers when the window is closed.
7. A raised exception that lands while a thread holds an emulator lock can deadlock; not seen yet.

Rendering:

8. The plate is drawn with a dotted pattern instead of solid studs.
9. About five draws per frame are skipped: `depth mips (DB_DEPTH_VIEW MIP_LEVEL) is unsupported`.
   Not confirmed to be the cause of item 8.
10. The ray-tracing compute shaders are not translated (they need the flat address apertures); none
    has been dispatched so far.
11. `DEPTH_CLEAR_ENABLE` draws still throw.

Checks owed on shared code (these changes affect Windows and Linux builds too):

12. Stencil clear behaviour and sRGB comparison sampling are assumptions, not measured on hardware.
13. `agc_driver_prepared_graphics` skipped itself here, so on-demand rect-list linking is covered only
    by the title running.
14. The relinker's convert-in-place rule and the heap capacity change have not been run on another host.

## How to measure

- Build: `cmake --build build --target libs relinker --parallel`, then
  `python3 tools/macos_launcher.py ~/Downloads/Lego`.
- Launch with `open --env APS5_PROFILE_DRAW=1 build/launcher/Lego.app`; the log is
  `~/Library/Logs/AnyPS5/PPSA05496.log`.
- Compare the mean of the `[present]` counts between 100 s and 240 s after launch. One 10-second
  line is not a measurement.
