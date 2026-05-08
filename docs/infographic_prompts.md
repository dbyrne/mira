# Infographic prompts

Drop-in prompts for ChatGPT's image generation (or any DALL-E-class
model) to produce three infographics for the Mira project:

1. **Project overview** — workflow at a glance (best for README hero)
2. **Setup steps** — first-time-user onboarding
3. **Concept glossary** — what the jargon means

All three share a single visual style so they can sit together in
docs/social posts without looking mismatched.

> **How to use**: copy the **Prompt** block from a section into ChatGPT.
> If the first attempt isn't quite right, see *Iteration tips* below
> each prompt. ChatGPT image generation often nails layout + style on
> the first try but garbles long text — keep iteration focused on
> getting labels readable, not on overhauling the design.

---

## Shared visual style

These attributes appear in every prompt below; if you want a totally
different look, edit them once at the top of each prompt before pasting:

- **Aspect / dimensions**: explicit per infographic (overview is
  horizontal, setup is vertical, glossary is square)
- **Background**: deep midnight navy (`#0a0e27`)
- **Primary accent**: warm amber-gold (`#f4b942`) — Mira is a red giant,
  so amber is thematically right
- **Secondary accent**: cool sky-blue (`#5b8fb9`)
- **Text**: soft cream (`#f5e9d3`)
- **Iconography**: simple flat / line icons with consistent stroke
  weight, never photographic
- **Texture**: very subtle scattered tiny gold dots suggesting a
  starfield, never busy or nebula-like
- **Vibe**: science magazine illustration, calm and professional —
  *not* gaming poster, *not* clichéd "Earth from space," *not* corporate
  stock-art

---

## 1. Project overview

**Use for**: the top of the README, a social media post introducing
the project, or a one-slide explainer for someone who's never heard
of variable-star photometry.

**Goal**: a viewer should grasp "what does this project do?" in
under 5 seconds.

### Prompt

```
Create a horizontal infographic, 1792x1024 pixels, titled "Mira: From Catalog to AAVSO Submission" with a subtitle "A backyard observing assistant for amateur variable-star photometry."

Style: clean modern flat illustration. Background is deep midnight navy (#0a0e27). Accents in warm amber-gold (#f4b942) and cool sky-blue (#5b8fb9). Text is soft cream (#f5e9d3). Subtle scattered tiny gold dots suggest a starfield without crowding the composition. Aesthetic is science magazine illustration, calm and professional.

The body of the infographic shows a left-to-right flow of 5 cards, each with a simple line icon at top, a single-word title in bold cream below the icon, and one short caption (under 10 words) below the title. Amber arrows connect the cards.

Card 1 — title "PICK" — icon: a magnifying glass hovering over a small star — caption: "Filter 10,000+ VSX targets to a tonight-worthy few."

Card 2 — title "PLAN" — icon: a clock face overlaid with a compass rose — caption: "Schedule around your sky, gear, and horizon."

Card 3 — title "CAPTURE" — icon: a stylized telescope on a tripod — caption: "NINA drives your scope through the plan automatically."

Card 4 — title "PROCESS" — icon: a small chart showing a brightness light curve — caption: "Differential photometry with AAVSO comparison stars."

Card 5 — title "SUBMIT" — icon: an envelope or upward upload arrow — caption: "AAVSO Extended File ready to upload."

Footer in lower right corner, small thin amber text: "github.com/dbyrne/mira"

Text labels must be short and large enough to read at thumbnail size. Avoid any long sentences in the image. The composition should breathe — generous spacing between cards, no visual clutter.
```

### Iteration tips

- If text inside the cards is garbled, ask: *"Re-render with simpler
  per-card text. Use only the single-word title — drop the captions
  entirely. I'll add captions in post."*
- If the icons all look the same: *"Make each icon visually distinct
  in shape and silhouette so they read at thumbnail size."*
- If the layout is too busy: *"Increase whitespace. Make each card
  occupy ~15% of the canvas width with generous padding."*
- If the colors look off: *"Pull the navy background slightly bluer
  and make the amber more saturated, like polished brass."*

---

## 2. Setup steps

**Use for**: the top of `docs/getting_started.md`, or as a thumbnail
on social posts that link to the tutorial.

**Goal**: someone unfamiliar with the project should see what's involved
in getting set up, and feel like the steps are achievable.

### Prompt

```
Create a vertical infographic, 1024x1792 pixels, titled "Getting Started with Mira" with a subtitle "From clean install to first AAVSO submission."

Style: clean modern flat illustration. Background deep midnight navy (#0a0e27). Accents in warm amber-gold (#f4b942) and cool sky-blue (#5b8fb9). Text in soft cream (#f5e9d3). Subtle starfield dots in the background, never busy. Aesthetic: science magazine illustration, calm and approachable.

The body shows 6 numbered steps stacked vertically, top to bottom. Each step is a horizontal row with a large amber numeral on the left (1 through 6), a simple line icon, a short bold step title, and a one-line description.

Step 1 — title "INSTALL" — icon: a terminal/code window — description: "Clone the repo. Run pip install. Done in 5 minutes."

Step 2 — title "CONFIGURE YOUR SITE" — icon: a globe with a map pin — description: "Drop in your latitude, longitude, and timezone."

Step 3 — title "MAP YOUR HORIZON" — icon: a phone showing a star overlay (representing Stellarium AR) — description: "Walk your balcony. Note where trees and rooftops block the sky."

Step 4 — title "DRESS REHEARSAL" — icon: a beaker or test tube — description: "Run the photometry pipeline on synthetic data. Catch issues before the real night."

Step 5 — title "FIRST OBSERVATION" — icon: a small telescope under stars — description: "Open the webapp. Watch NINA work through the schedule."

Step 6 — title "SUBMIT TO AAVSO" — icon: an envelope with a checkmark — description: "Upload your AAVSO file. Your data joins a century of variable-star records."

Footer at bottom center, small thin amber text: "github.com/dbyrne/mira"

Numerals on the left should be large and prominent. Each step should clearly belong to its row — easy to follow vertically. Keep on-image text short; the descriptions should fit on one line each.
```

### Iteration tips

- If steps blur together: *"Add subtle horizontal divider lines between
  each step row in dim sky-blue."*
- If numerals are too small: *"Make the step numerals huge — about 80%
  the height of each row — to anchor each step visually."*
- If you want the icons emphasized over the text: *"Move the icons to
  be slightly larger than the text labels. The icon should be the
  visual focal point of each row."*

---

## 3. Concept glossary

**Use for**: link from `docs/concepts.md` as a visual companion, or
embed in slides explaining the project to non-astronomers.

**Goal**: someone unfamiliar with VSX, comp stars, plate-solving, etc.
gets a one-line definition for each in a single glance.

### Prompt

```
Create a square infographic, 1024x1024 pixels, titled "Mira — Key Terms" with a subtitle "Variable-star photometry vocabulary, in plain English."

Style: clean modern flat illustration. Background deep midnight navy (#0a0e27). Accents in warm amber-gold (#f4b942) and cool sky-blue (#5b8fb9). Text in soft cream (#f5e9d3). Subtle starfield dots in the background, sparse and not distracting. Aesthetic: scientific dictionary plate, organized and calm.

The body is a 3x3 grid of 9 terminology cards. Each card has a small line icon at top, a single bold term in cream, and a one-sentence definition below in smaller cream text.

Card 1 — term: "VARIABLE STAR" — icon: a star with concentric brightness rings around it — definition: "A star whose brightness changes over time."

Card 2 — term: "VSX" — icon: a small catalog/book icon with a star — definition: "AAVSO's master catalog of 2 million variable stars."

Card 3 — term: "COMP STAR" — icon: two stars with a balance scale between them — definition: "A nearby star of known brightness used for comparison."

Card 4 — term: "DIFFERENTIAL PHOTOMETRY" — icon: two stars with a brightness ratio symbol — definition: "Measuring brightness relative to a comp star, not in absolute terms."

Card 5 — term: "ENSEMBLE" — icon: three stars connected by lines forming a triangle — definition: "Using multiple comp stars at once for robustness."

Card 6 — term: "PLATE-SOLVING" — icon: a grid overlaid on a star field — definition: "Matching captured stars to a catalog to know exactly where the scope is pointed."

Card 7 — term: "FITS" — icon: a stylized image-file rectangle with a small star — definition: "The standard astronomical image file format."

Card 8 — term: "AAVSO" — icon: a globe with an envelope or upload arrow — definition: "The American Association of Variable Star Observers — where submissions go."

Card 9 — term: "ANOMALY" — icon: a star with a small alert/exclamation symbol — definition: "When measured brightness meaningfully differs from expectation."

Footer in the corner, thin amber: "github.com/dbyrne/mira"

The 3x3 grid should be evenly spaced with clear visual separation between cards. Icons should be visually distinct from each other. Definitions should fit on at most two lines per card.
```

### Iteration tips

- If text is garbled, this is the prompt most likely to suffer because
  there are 9 captions. Ask: *"Drop the definitions. Keep only the
  terms and icons. I'll add definitions in post-production."*
- If you want a different term set: replace any of the 9 terms in the
  prompt directly before pasting. Good additional candidates: *Gaia
  DR3, ZTF, MAD, Lomb-Scargle, AAVSO Extended File, observer code, TG
  band*.
- If you want grouping by category: *"Reorganize the grid so left
  column is catalogs (VSX, AAVSO, ZTF), middle is photometry (comp
  star, ensemble, differential), right is observing (FITS, plate-solving,
  altitude). Add subtle column headers."*

---

## Tips for ChatGPT image generation in general

- **Iterate, don't restart.** "Make the icons larger" produces better
  results than re-running the whole prompt with a new wording.
- **One change per iteration.** "Bigger numerals AND change the colors"
  often makes the model do neither well.
- **Keep on-image text short.** Long sentences get garbled. If you
  need a paragraph of explanation, generate the visual without text
  and add the text in a graphics tool afterward.
- **DALL-E loves specifics.** "A telescope" is worse than "a stylized
  refractor telescope on a wooden tripod, line illustration."
- **Save the system prompt + final iteration** as a comment in this
  file so the next infographic generation can match the established
  style.
