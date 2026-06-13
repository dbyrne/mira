# NGC 7000 (North America) -- overnight processing log

- 2026-06-13 04:49:52 UTC -- watcher started; mira at C:\Users\david\AppData\Local\Programs\Python\Python311\Scripts\mira.exe
- 2026-06-13 07:51:55 UTC -- capture done: 155 frames, last frame 6 min ago
- 2026-06-13 07:51:55 UTC -- === begin reduction: 155 light frames ===
- 2026-06-13 07:51:55 UTC -- solve: start
- 2026-06-13 07:52:04 UTC -- solve: exit 2
- 2026-06-13 07:52:04 UTC -- cull: start
- 2026-06-13 07:52:49 UTC -- cull: exit 0
- 2026-06-13 07:52:49 UTC -- cull: 51 kept / 104 rejected
- 2026-06-13 07:52:49 UTC -- stack: start -> C:\mira\output\processed\ngc7000\NGC7000_stack_20260613.fit
- 2026-06-13 07:53:05 UTC -- stack: exit 0
- 2026-06-13 07:53:05 UTC -- stack OK (95 MB)
- 2026-06-13 07:53:05 UTC -- finish(emission): start -> C:\mira\output\processed\ngc7000\NGC7000_emission_20260613.png
- 2026-06-13 07:53:43 UTC -- finish: exit 0
- 2026-06-13 07:53:43 UTC -- finish OK -> C:\mira\output\processed\ngc7000\NGC7000_emission_20260613.png
- 2026-06-13 07:53:43 UTC -- === DONE ===

---

## Review summary (2026-06-13, post-run analysis)

**Session:** NGC 7000 (North America), S30 Pro, LP dual-band, gain 80, 60s subs, EQ/polar-aligned. `--platesolve-center`, mount slew-dither every sub.

**Capture:** 155 subs to dawn auto-stop (sun > -15 deg). Pointing solved to RA 314.685 / Dec +44.331 — within 0.01 deg of catalog (314.696 / +44.330). Dead-centered.

**Clouds cut the night:** a bank moved through ~01:00-02:30. Solve→cull caught it cleanly:
- 61 frames unsolvable ("No solution found", stars=1-3, HFR 7+) = clouded.
- 43 more culled on HFR/stars/roundness (cloud-edge / soft).
- **51 of 155 kept = ~51 min clean integration.** (The solve-before-cull order earned its keep here.)

**Stack:** 51 frames, OSC debayer (RGGB) + LP_g80 auto-flat. Clean registration (round single stars). Faint nebula under an LP gradient — expected for 51 min on a 30mm scope.

**Finish — two renders:**
- `NGC7000_emission_20260613.*` — the `emission` HOO preset. **Over-cooked:** the preset skips GraXpert denoise (validated on *deep* data), so on thin signal it amplified per-pixel noise into RGB chroma confetti. Not usable.
- `NGC7000_denoised_20260613.*` — **THE KEEPER.** Non-preset path: GraXpert background-extraction (killed the gradient) + GraXpert AI denoise + Siril autostretch + sat 0.20, no deconv (no SNR to spare). Smooth background, clean stars, honest faint detection.

**Verdict:** clean, well-framed, real detection of North America — but clouds robbed it of keeper-grade depth. Not a portfolio image at 51 min.

**Recommendation:** re-shoot on the next clear moonless night for 2-3+ hr. Tonight's 51 clean subs are NOT wasted — same rig/filter/target, so they co-register and stack with a future session to build total integration. Keep `captures/ngc7000_20260613/` (the 51 kept frames + `_rejected/`).
