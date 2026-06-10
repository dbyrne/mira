"""Tests for finish_presets — the baked 2026-06-09 reprocessing recipes.

Pure-math ops are pinned (no StarNet, no GraXpert, no network). The
invariants tested here are the ones the session's adversarial verification
established as the *reasons* the recipes are honest:

  * gated chroma denoise is exactly luminance-preserving;
  * luminance-preserving SCNR preserves luminance (plain SCNR does not);
  * the noise toe is monotonic, fixes f(1)=1, and suppresses below-toe
    values quadratically while leaving well-above-toe values ~unchanged;
  * the pedestal is a pure levels move (order-preserving, no new clipping);
  * preset registry carries the verified parameter anchors.
"""
import unittest

import numpy as np

from mira import finish_presets as fp


def _rng_image(h=64, w=64, seed=7):
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.0, 0.2, size=(h, w, 3))
    base[20:30, 20:30] += 0.5  # a bright structure
    return np.clip(base, 0, 1)


class SmoothstepTests(unittest.TestCase):
    def test_bounds_and_direction(self):
        x = np.linspace(-1, 2, 50)
        y = fp.smoothstep(0.0, 1.0, x)
        self.assertTrue(np.all(y >= 0) and np.all(y <= 1))
        self.assertEqual(y[0], 0.0)
        self.assertEqual(y[-1], 1.0)
        self.assertTrue(np.all(np.diff(y) >= -1e-12))

    def test_reversed_edges_gate_high_to_low(self):
        # smoothstep(hi, lo, x) is the "1 in the faint zone" form used by the
        # chroma gate: below lo -> 1, above hi -> 0.
        y = fp.smoothstep(0.2, 0.1, np.array([0.05, 0.3]))
        self.assertAlmostEqual(float(y[0]), 1.0)
        self.assertAlmostEqual(float(y[1]), 0.0)


class NoiseToeTests(unittest.TestCase):
    def test_endpoint_fixed(self):
        self.assertAlmostEqual(float(fp.noise_toe(np.array([1.0]), 0.01)[0]), 1.0, places=12)

    def test_monotonic(self):
        x = np.linspace(0, 1, 200)
        y = fp.noise_toe(x, 0.01)
        self.assertTrue(np.all(np.diff(y) >= 0))

    def test_suppresses_below_toe_keeps_above(self):
        toe = 0.01
        below = float(fp.noise_toe(np.array([toe / 2]), toe)[0])
        above = float(fp.noise_toe(np.array([toe * 20]), toe)[0])
        self.assertLess(below, toe / 2 * 0.6)          # strongly suppressed
        self.assertGreater(above, toe * 20 * 0.95)     # ~unchanged

    def test_zero_toe_is_identity(self):
        x = np.linspace(0, 1, 11)
        np.testing.assert_allclose(fp.noise_toe(x, 0.0), x)


class ChromaDenoiseTests(unittest.TestCase):
    def test_luminance_exactly_preserved(self):
        img = _rng_image()
        out = fp.gated_chroma_denoise(img, gate_lo=0.10, gate_hi=0.25, sigma=3.0, keep=0.3)
        np.testing.assert_allclose(out.mean(-1), img.mean(-1), atol=1e-9)

    def test_bright_zone_untouched(self):
        img = _rng_image()
        out = fp.gated_chroma_denoise(img, gate_lo=0.01, gate_hi=0.02, sigma=3.0, keep=0.0)
        bright = img.mean(-1) > 0.4
        np.testing.assert_allclose(out[bright], img[bright], atol=1e-9)

    def test_faint_zone_chroma_reduced(self):
        img = _rng_image()
        out = fp.gated_chroma_denoise(img, gate_lo=0.30, gate_hi=0.40, sigma=4.0, keep=0.0)
        faint = img.mean(-1) < 0.25
        chroma_in = np.abs(img - img.mean(-1, keepdims=True))[faint].mean()
        chroma_out = np.abs(out - out.mean(-1, keepdims=True))[faint].mean()
        self.assertLess(chroma_out, chroma_in * 0.2)


class ScnrTests(unittest.TestCase):
    def test_keep_lum_preserves_luminance(self):
        img = _rng_image()
        img[..., 1] += 0.1  # green cast
        img = np.clip(img, 0, 1)
        out = fp.scnr_green(img, 0.8, keep_lum=True)
        np.testing.assert_allclose(out.mean(-1), img.mean(-1), atol=1e-6)

    def test_plain_scnr_lowers_green_and_luminance(self):
        img = np.full((8, 8, 3), 0.2)
        img[..., 1] = 0.5
        out = fp.scnr_green(img, 1.0, keep_lum=False)
        self.assertTrue(np.all(out[..., 1] <= 0.2 + 1e-9))
        self.assertLess(float(out.mean()), float(img.mean()))

    def test_zero_amount_identity(self):
        img = _rng_image()
        np.testing.assert_allclose(fp.scnr_green(img, 0.0), img)


class PedestalTests(unittest.TestCase):
    def test_levels_move_order_preserving_no_clip(self):
        img = _rng_image()
        out = fp.pedestal(img, 0.045)
        self.assertGreaterEqual(float(out.min()), 0.045 - 1e-9)
        self.assertLessEqual(float(out.max()), 1.0)
        a, b = img[0, 0, 0], img[10, 10, 0]
        oa, ob = out[0, 0, 0], out[10, 10, 0]
        self.assertEqual(a < b, oa < ob)
        # exact contrast scale (1 - p): the M81 "95.4% detail" arithmetic
        np.testing.assert_allclose(ob - oa, (b - a) * (1 - 0.045), atol=1e-12)


class ScreenAndStarToneTests(unittest.TestCase):
    def test_screen_bounds_and_identity(self):
        a, b = _rng_image(seed=1), _rng_image(seed=2)
        out = fp.screen(a, b)
        self.assertTrue(np.all(out >= np.maximum(a, b) - 1e-9))
        self.assertTrue(np.all(out <= 1.0))
        np.testing.assert_allclose(fp.screen(a, np.zeros_like(a)), a)

    def test_star_tone_thins_faint_more_than_bright(self):
        stars = np.zeros((4, 4, 3))
        stars[0, 0] = 0.1   # faint star
        stars[1, 1] = 0.9   # bright star
        out = fp.star_tone(stars, gamma=1.7, scale=0.95, sat=1.0)
        faint_ratio = out[0, 0, 0] / 0.1
        bright_ratio = out[1, 1, 0] / 0.9
        self.assertLess(faint_ratio, bright_ratio)


class BgNeutralizeTests(unittest.TestCase):
    def test_offsets_equalize_bg_channel_medians(self):
        rng = np.random.default_rng(3)
        img = np.clip(rng.normal(0.10, 0.01, (64, 64, 3)), 0, 1)
        img[..., 2] += 0.05  # blue cast
        img = np.clip(img, 0, 1)
        out = fp.bg_neutralize_offset(img, pct=80.0, target=None)
        lum = out.mean(-1)
        m = lum < np.percentile(lum, 80.0)
        meds = [float(np.median(out[..., c][m])) for c in range(3)]
        self.assertLess(max(meds) - min(meds), 0.005)


class RolloffTests(unittest.TestCase):
    def test_continuous_at_knee_and_capped(self):
        k = 0.62
        eps = 1e-6
        lo = float(fp.highlight_rolloff(np.array([k - eps]), k)[0])
        hi = float(fp.highlight_rolloff(np.array([k + eps]), k)[0])
        self.assertAlmostEqual(lo, hi, places=4)
        top = float(fp.highlight_rolloff(np.array([1.0]), k)[0])
        self.assertLess(top, 0.87)   # caps ~0.86, never clips
        self.assertGreater(top, 0.84)


class DecomposeFallbackTests(unittest.TestCase):
    def test_morphological_split_removes_point_sources(self):
        img = np.full((64, 64, 3), 0.05)
        img[10:40, 10:40] += 0.2          # extended structure
        img[20, 50] = img[50, 20] = 1.0   # point "stars"
        starless, stars = fp._morphological_decompose(img)
        self.assertLess(float(starless[20, 50, 0]), 0.3)
        self.assertGreater(float(stars[20, 50, 0]), 0.5)
        self.assertGreater(float(starless[25, 25, 0]), 0.2)
        np.testing.assert_allclose(starless + stars, img, atol=1e-9)

    def test_small_frame_uses_fallback_without_starnet(self):
        img = _rng_image(h=64, w=64)
        starless, stars = fp.starnet_decompose(img, exe=None, allow_fallback=False)
        self.assertEqual(starless.shape, img.shape)


class PresetRegistryTests(unittest.TestCase):
    def test_three_presets_with_verified_anchors(self):
        self.assertEqual(set(fp.PRESETS), {"faint-galaxy", "faint-galaxy-deep", "emission"})
        deep = fp.PRESETS["faint-galaxy-deep"].params
        self.assertEqual(deep["dig_b"], 0.014)           # M81 conservative row
        self.assertEqual(deep["asinh_a"], 0.025)
        self.assertEqual(deep["star_gain"], 1.0)         # no star dimming (verifier)
        em = fp.PRESETS["emission"].params
        self.assertEqual(em["white_pct"], 99.6)          # the Crescent white-point lesson
        self.assertEqual(em["rolloff_k"], 0.62)          # Ha-blowout fix
        self.assertEqual(em["roll_lo"], 0.62)            # knots-only desat
        fg = fp.PRESETS["faint-galaxy"].params
        self.assertEqual(fg["bp_soft_sigma"], 4.0)       # soft black point
        self.assertFalse(fp.PRESETS["faint-galaxy"].needs_starnet)

    def test_unknown_override_rejected_with_valid_list(self):
        img = _rng_image()
        with self.assertRaises(KeyError):
            fp.render_preset(img, "faint-galaxy", overrides={"bogus_knob": 1.0})

    def test_faint_galaxy_renders_end_to_end(self):
        # small synthetic frame through the full no-StarNet preset
        out = fp.render_preset(_rng_image(), "faint-galaxy")
        self.assertEqual(out.shape, (64, 64, 3))
        self.assertTrue(np.all(out >= 0) and np.all(out <= 1))


if __name__ == "__main__":
    unittest.main()
