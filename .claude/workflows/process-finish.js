export const meta = {
  name: 'process-finish',
  description: 'Stretch-curve shootout: copy the curvelab harness to a workdir, re-tune 6 custom curves for the target, judge-panel + adversarial-verify vs an asinh baseline. Args: {target, baseFits, mode:"faint"|"chroma", ra, dec, baseline:{params,desc}, feat:{ra,dec}, rim, halo, sky, sat, cropHalf, workDir, techniques}',
  phases: [
    { title: 'Setup', detail: 'copy harness+curves to workdir, render asinh baseline' },
    { title: 'Curves', detail: 'one agent per curve: re-tune for the target, sweep' },
    { title: 'Judge', detail: '3-lens panel scores previews vs baseline' },
    { title: 'Verify', detail: 'adversarial refute of the winner' },
  ],
}

let T = args || {}
if (typeof T === 'string') { try { T = JSON.parse(T) } catch (e) { T = {} } }
if (!T || !T.baseFits) { T = {target:'NGC6888', baseFits:'C:/mira/output/ngc6888/ngc6888_cc.fit', mode:'chroma', ra:303.0, dec:38.35, rim:'40,170', halo:'170,250', sky:'320,500', cropHalf:380, sat:1.9, baseline:{params:'a=0.012', desc:'asinh a=0.012'}} }
const target = T.target || 'target'
const BASE = T.baseFits
const mode = T.mode === 'chroma' ? 'chroma' : 'faint'
const ra = T.ra, dec = T.dec
if (!BASE || ra === undefined || dec === undefined) {
  return { error: 'args needs {baseFits, ra, dec}; optional {target, mode:"faint"|"chroma", baseline:{params,desc}, feat:{ra,dec}, rim, halo, sky, sat, cropHalf, workDir, techniques}' }
}
const sat = T.sat || (mode === 'chroma' ? 1.9 : 1.4)
const cropHalf = T.cropHalf || (mode === 'chroma' ? 160 : 420)
const baseParams = (T.baseline && T.baseline.params) || (mode === 'chroma' ? 'a=0.15' : 'a=0.025')
const baseDesc = (T.baseline && T.baseline.desc) || ('asinh ' + baseParams)
const feat = (T.feat && T.feat.ra !== undefined) ? `--feat-ra ${T.feat.ra} --feat-dec ${T.feat.dec}` : ''
const rim = T.rim ? `--rim ${T.rim}` : ''
const halo = T.halo ? `--halo ${T.halo}` : ''
const sky = T.sky ? `--sky ${T.sky}` : ''
const geom = `--mode ${mode} --ra ${ra} --dec ${dec} ${feat} ${rim} ${halo} ${sky} --sat ${sat} --crop-half ${cropHalf}`.replace(/\s+/g, ' ').trim()
const SKILL_LAB = 'C:/mira/.claude/skills/mira-finish/curvelab'
const WORK = T.workDir || `C:/mira/output/${target}_curveshootout`
const TECHNIQUES = T.techniques || ['ghs', 'masked', 'statistical', 'arctan', 'loghist', 'localcontrast', 'owleyes']

const STAT_HELP = mode === 'chroma'
  ? 'Stats: rim_chroma (PRIMARY -- ring color kept), rim_lum (ring brightness), rim_clip (blown-white frac), center_chroma, halo_contrast/halo_lum/sky_lum, sky_noise_lum, sky_noise_chroma, midtone, lin_rim_snr/lin_halo_snr (curve-invariant anchors, ignore for ranking).'
  : 'Stats: faint_detect (PRIMARY -- faint feature above sky), faint_contrast, sky_disp, sky_noise_disp, core_clip, frame_clip, midtone, lin_feat_snr (curve-invariant anchor, ignore for ranking).'
const GOAL = mode === 'chroma'
  ? `GOAL: beat the baseline (${baseDesc}) -- HIGHER rim_chroma (more OIII-teal/Ha-red color in the bright rim) WITHOUT dimming the ring (keep rim_lum within ~15% of baseline), blowing it (rim_clip ~0), or raising sky_noise_lum/sky_noise_chroma above baseline. Do NOT chase halo_contrast if lin_halo_snr is tiny. Oversaturating ONE hue, dimming, or sky mottle does NOT count -- multi-hue color must be honest.`
  : `GOAL: beat the baseline (${baseDesc}) -- HIGHER faint_detect (faint feature lifted further above sky) at sky_noise_disp NO WORSE than baseline and core_clip ~0 (cores not blown). Brightening everything (high midtone+noise) or crushing the sky to game the denominator does NOT count.`

const CONTRACT = `
The harness curve_lab.py (in ${WORK}, copied from the validated library) runs a FIXED pipeline so variants differ ONLY in the tone curve:
  load linear FITS -> per-channel sky-median black -> global white normalize to [0,1] -> YOUR curve apply(x) -> saturation ${sat} -> PNG/preview + display-space stats.
Your plugin ALREADY EXISTS at ${WORK}/curves/<NAME>.py (validated math). ADAPT + RE-TUNE its DEFAULTS/SWEEP for THIS target/regime (tweak apply() only if the regime needs a knob it lacks; keep the contract: DEFAULTS, SWEEP, apply(x,**p)->(H,W,3) in [0,1]). Only edit YOUR curves/<NAME>.py; do NOT touch curve_lab.py, curves/asinh.py, or other curves (parallel agents).
Run (bash, forward-slash paths work):
  cd ${WORK} && python curve_lab.py --in ${BASE} --curve <NAME> ${geom} --selftest
  cd ${WORK} && python curve_lab.py --in ${BASE} --curve <NAME> ${geom} --sweep
--sweep prints one JSON row per param set and writes variants/<NAME>/manifest.json + previews. Report your best row's "prev" path.
${STAT_HELP}
${GOAL}
A tone curve cannot change linear SNR -- these stats are display-space and the metric is a SERVANT: corroborate by eye, never game it.
`

phase('Setup')
const SETUP = {
  type: 'object', additionalProperties: false, required: ['ready', 'baseline_prev', 'baseline_stats'],
  properties: { ready: { type: 'boolean' }, baseline_prev: { type: 'string' }, baseline_stats: { type: 'object', additionalProperties: { type: 'number' } }, note: { type: 'string' } },
}
const setup = await agent(
  `Set up a curve-shootout working dir and render the baseline.\n` +
  `1. mkdir -p ${WORK} then copy the harness + curve library in (NOT any variants/):\n` +
  `   cp -r ${SKILL_LAB}/curve_lab.py ${SKILL_LAB}/curves ${WORK}/\n` +
  `2. Render the asinh baseline (the bar to beat):\n` +
  `   cd ${WORK} && python curve_lab.py --in ${BASE} --curve asinh ${geom} --params "${baseParams}" --keep\n` +
  `3. Return ready=true, the baseline preview path (the "prev" field printed, like ${WORK}/variants/asinh/asinh__<slug>_prev.png), and the baseline stats dict.`,
  { label: 'setup', phase: 'Setup', schema: SETUP }
).catch(() => null)
if (!setup || !setup.ready) return { error: 'setup failed', setup }
log(`baseline ready (${mode}): ${JSON.stringify(setup.baseline_stats)}`)

phase('Curves')
const CURVE_RESULT = {
  type: 'object', additionalProperties: false, required: ['name', 'selftest_ok', 'best_params', 'best_stats', 'preview_path', 'beats_baseline'],
  properties: { name: { type: 'string' }, changes: { type: 'string' }, selftest_ok: { type: 'boolean' }, best_params: { type: 'object', additionalProperties: { type: 'number' } }, best_stats: { type: 'object', additionalProperties: { type: 'number' } }, preview_path: { type: 'string' }, beats_baseline: { type: 'boolean' }, notes: { type: 'string' } },
}
const curves = await parallel(TECHNIQUES.map(name => () =>
  agent(
    `Adapt + re-tune ONE stretch curve for a controlled shootout on ${target} (${mode} regime).\n` +
    `YOUR CURVE: "${name}" (plugin at ${WORK}/curves/${name}.py).\n\n` + CONTRACT +
    `\nResearch the regime if useful (web available), re-tune params, self-test, then sweep. Report best param set, full stats dict, the best row's preview_path, what you changed, and whether it HONESTLY beats the baseline.`,
    { label: `curve:${name}`, phase: 'Curves', schema: CURVE_RESULT }
  ).catch(() => null)
))
const ok = curves.filter(c => c && c.selftest_ok && c.preview_path)
log(`${ok.length}/${TECHNIQUES.length} curves swept: ${ok.map(c => c.name).join(', ')}`)
if (!ok.length) return { error: 'no curves implemented', curves }
const slate = ok.map(c => `- ${c.name}: ${JSON.stringify(c.best_stats)}\n    preview: ${c.preview_path}`).join('\n')

phase('Judge')
const LENSES = mode === 'chroma'
  ? ['RING COLOR RICHNESS: vivid, well-separated OIII-teal body + Ha-red rim + cavity color; NOT a flat oversaturated cast or blown white.',
     'RING BRIGHTNESS & STRUCTURE: bright, clearly rendered ring (not dimmed to win color); rim + central hole visible; rim not blown white.',
     'SKY & ARTIFACTS: clean dark sky, natural star color, NO chroma mottle, NO dark-moat/bright-halo ring around the rim, no color cast.']
  : ['FAINT-STRUCTURE RECOVERY: how much genuine faint structure (tidal features, outer arms, low-SB halo) is visible above sky.',
     'CORE / STAR / COLOR FIDELITY: cores not blown white, natural star color, no halos/rings, no global cast.',
     'NOISE & ARTIFACTS: amplified/mottled background, banding/posterization, plastic over-smoothing, local-contrast haloing, ringing.']
const JUDGE = {
  type: 'object', additionalProperties: false, required: ['lens', 'ranking'],
  properties: { lens: { type: 'string' }, ranking: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['name', 'score'], properties: { name: { type: 'string' }, score: { type: 'number' }, reason: { type: 'string' } } } }, overall_notes: { type: 'string' } },
}
const judges = await parallel(LENSES.map((lens, i) => () =>
  agent(
    `You are judge ${i + 1} of 3 in a ${target} stretch-curve shootout. Score every candidate 0-10 STRICTLY through THIS lens:\n${lens}\n\n` +
    `Baseline (bar to beat) preview: ${setup.baseline_prev}\nBaseline stats: ${JSON.stringify(setup.baseline_stats)}\n\n` +
    `Candidates -- Read EACH preview image with the Read tool before scoring:\n${slate}\n\n` +
    `Read the baseline AND every candidate. Include the baseline as "asinh-baseline" in your ranking. Rank best-first with a 0-10 score and a one-line reason citing what you SEE.`,
    { label: `judge:${i + 1}`, phase: 'Judge', schema: JUDGE }
  ).catch(() => null)
))
const gj = judges.filter(Boolean)
const sc = {}
gj.forEach((j, ji) => {
  for (const r of (j.ranking || [])) {
    if (!r || !r.name) continue
    sc[r.name] = sc[r.name] || { name: r.name, total: 0, n: 0, reasons: [] }
    sc[r.name].total += (typeof r.score === 'number' ? r.score : 0)
    sc[r.name].n += 1
    if (r.reason) sc[r.name].reasons.push(`J${ji + 1}: ${r.reason}`)
  }
})
const ranked = Object.values(sc).map(s => ({ name: s.name, avg: +(s.total / Math.max(1, s.n)).toFixed(2), reasons: s.reasons })).sort((a, b) => b.avg - a.avg)
log(`panel: ${ranked.map(r => `${r.name}=${r.avg}`).join('  ')}`)
const baseAvg = (ranked.find(r => r.name === 'asinh-baseline') || {}).avg
const winRow = ranked.find(r => r.name !== 'asinh-baseline')
const topCurve = winRow ? ok.find(c => c.name === winRow.name) : null

phase('Verify')
const VERDICT = {
  type: 'object', additionalProperties: false, required: ['winner', 'is_real_improvement', 'confidence', 'verdict'],
  properties: { winner: { type: 'string' }, is_real_improvement: { type: 'boolean' }, confidence: { type: 'number' }, issues: { type: 'array', items: { type: 'string' } }, verdict: { type: 'string' } },
}
let verdict = null
if (topCurve) {
  const winFull = topCurve.preview_path.replace('_prev.png', '.png')
  const baseFull = setup.baseline_prev.replace('_prev.png', '.png')
  const checks = mode === 'chroma'
    ? '(1) extra color REAL (more hue separation) or just oversaturation/cast/hue-shift? (2) rim blown white anywhere? (3) dark-moat/bright-halo ring around the rim? (4) sky chroma mottle? (5) won only by DIMMING the ring? (6) does the rim_chroma gain correspond to something you SEE?'
    : '(1) extra faint structure REAL or amplified noise/pattern? (2) banding/posterization from over-stretch? (3) cores blown to white? (4) star halos/rings, plastic smoothing, color cast? (5) does the faint_detect gain correspond to something you SEE?'
  verdict = await agent(
    `Adversarial verification of a ${target} curve-shootout winner (${mode} regime). Default SKEPTICAL -- try to REFUTE "the winner genuinely beats the asinh baseline with no artifacts."\n` +
    `Winner "${topCurve.name}" params ${JSON.stringify(topCurve.best_params)} stats ${JSON.stringify(topCurve.best_stats)}. Panel: winner ${winRow.avg} vs baseline ${baseAvg}.\n` +
    `Read BOTH full-res images with the Read tool:\n  winner: ${winFull}\n  baseline: ${baseFull}\n\n` +
    `Check: ${checks}\nReturn is_real_improvement (true ONLY if it survives), confidence 0-1, issues found, and a one-paragraph verdict.`,
    { label: 'verify:winner', phase: 'Verify', schema: VERDICT }
  ).catch(() => null)
}

return {
  target, mode, baseline: baseDesc, baseline_panel_avg: baseAvg,
  curves: ok.map(c => ({ name: c.name, beats_baseline: c.beats_baseline, best_params: c.best_params, best_stats: c.best_stats, preview: c.preview_path, notes: c.notes })),
  panel_ranking: ranked,
  winner: winRow ? winRow.name : null,
  winner_vs_baseline: winRow ? `${winRow.avg} vs ${baseAvg}` : null,
  verdict,
}
