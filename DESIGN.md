# DESIGN.md — SecondMind

> A tournament hall at midnight: deep ink, one warm gold light, and every move in focus.

## 1. Visual Theme & Atmosphere

**Style**: Midnight Gold (Dark Tech palette, restrained like Minimal Pure)
**Keywords**: deep, focused, premium, calm, precise, warm-lit, strategic
**Tone**: confident and quiet, like a coach who knows the answer, NOT neon, gamer, cyberpunk or flashy
**Feel**: a dark wooden analysis room where one brass lamp lights the board.

**Interaction Tier**: L2, smooth interaction (scroll reveals, animated hero background, spotlight cards, nav that changes on scroll). App pages stay calm: motion only for feedback.
**Dependencies**: CSS + IntersectionObserver only (no GSAP / Lenis). React 18 + Vite.

Gold is the only accent colour and marks one thing per view: the main action or the current selection. Chess meaning stays in its own colours: green good, red bad, amber warning, blue "engine / suggestion".

## 2. Color Palette & Roles

```css
:root {
  /* Backgrounds */
  --bg: #0b0e14;              /* page */
  --bg-deep: #07090d;         /* footer, wells, inputs */
  --surface: #131823;         /* cards, panels */
  --surface-alt: #1a2030;     /* raised panels, table heads, alternating sections */
  --surface-hover: #212a3d;   /* hovered surface */

  /* Borders */
  --border: #232b3b;
  --border-hover: #36415a;

  /* Text */
  --text: #eef1f6;            /* headings, key text (15.9:1 on --bg) */
  --text-secondary: #b4bccb;  /* body copy (9.6:1) */
  --text-tertiary: #8a93a6;   /* labels, meta (5.9:1) */

  /* Accent: gold */
  --accent: #e8b04b;
  --accent-hover: #f2c46a;
  --accent-strong: #c98f26;   /* pressed */
  --on-accent: #1a1204;       /* text on gold buttons (10.8:1) */

  /* Chess semantics */
  --success: #4ade80;         /* good move, in book, won */
  --error: #f26d6d;           /* mistake, lost, you left the book */
  --warning: #f5a524;         /* inaccuracy, gaps, opponent surprise */
  --info: #6aa8ff;            /* engine / Stockfish suggestion */

  /* Board */
  --board-light: #dfe4ec;
  --board-dark: #7d8ea8;

  /* RGB helpers for rgba() */
  --bg-rgb: 11, 14, 20;
  --surface-rgb: 19, 24, 35;
  --accent-rgb: 232, 176, 75;
  --success-rgb: 74, 222, 128;
  --error-rgb: 242, 109, 109;
  --warning-rgb: 245, 165, 36;
  --info-rgb: 106, 168, 255;
}

/* Daylight variant (theme toggle): same roles, light values */
:root[data-theme="light"] {
  --bg: #f6f4ef; --bg-deep: #ece8df; --surface: #ffffff; --surface-alt: #f8f6f1; --surface-hover: #f0ece3;
  --border: #e2ddd2; --border-hover: #cfc7b6;
  --text: #15181f; --text-secondary: #3c4250; --text-tertiary: #646b7a;
  --accent: #a8730f; --accent-hover: #8f610a; --accent-strong: #75500a; --on-accent: #ffffff;
  --success: #1f8a4c; --error: #c23b3b; --warning: #b26a00; --info: #2563c9;
  --bg-rgb: 246, 244, 239; --surface-rgb: 255, 255, 255; --accent-rgb: 168, 115, 15;
  --success-rgb: 31, 138, 76; --error-rgb: 194, 59, 59; --warning-rgb: 178, 106, 0; --info-rgb: 37, 99, 201;
}
```

**Color Rules:**
- Every colour in components comes from these variables, with no hex in component CSS or JSX. Tints use `rgba(var(--x-rgb), a)`.
- Gold is used for one primary action per view, the active nav item and the current selection. Never for body text or large fills.
- Move arrows: red = what you played, green = your repertoire / correct move, blue = engine suggestion, amber = an opponent move you have not prepared.
- Tints for state backgrounds are 10–18% alpha of the semantic colour; text on them uses the full colour.
- Board colours are only `--board-light` / `--board-dark` (also in the light theme).

## 3. Typography Rules

**Font Stack:**
```css
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&display=swap');
--font-display: "Space Grotesk", "Inter", system-ui, sans-serif;
--font-body: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
--font-mono: "JetBrains Mono", ui-monospace, "Cascadia Mono", monospace;
```

| Role | Font | Size | Weight | Line Height | Letter Spacing |
|------|------|------|--------|-------------|----------------|
| Hero H1 | Space Grotesk | clamp(2.8rem, 6.4vw, 5.2rem) | 700 | 1.02 | -0.035em |
| Section H2 | Space Grotesk | clamp(1.9rem, 3.4vw, 2.8rem) | 700 | 1.1 | -0.025em |
| Page H2 (app) | Space Grotesk | 1.6rem | 600 | 1.2 | -0.015em |
| H3 | Space Grotesk | 1.15rem | 600 | 1.3 | -0.01em |
| Body | Inter | 0.95rem (15.2px) | 400 | 1.6 | — |
| Lead | Inter | 1.15rem | 400 | 1.65 | — |
| Label / eyebrow | Inter | 0.75rem | 600 | 1.3 | 0.12em, uppercase |
| Moves / evals | JetBrains Mono | 0.88rem | 500 | 1.4 | tabular-nums |

**Typography Rules:**
- Headings in Space Grotesk 600–700, never lighter. Body always Inter 400–500.
- Chess moves, scores and percentages use `--font-mono` or `font-variant-numeric: tabular-nums` so columns align.
- One H1 per page. App pages start with a Page H2.
- **NEVER use**: Roboto, Arial as a chosen font, Comic Sans, Orbitron or any display font for body text, all-caps paragraphs.

**Text Decoration:**
- Hero H1: one word ("Mind") filled with a slow moving gold gradient (`background-clip: text`). No drop shadow.
- Section H2: plain `--text`; eyebrow above in gold. No gradients.
- App headings: plain, no decoration.

## 4. Component Stylings

### Buttons
```css
button, .btn {
  font: 500 0.92rem/1 var(--font-body); min-height: 40px; padding: 0 16px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--surface-alt); color: var(--text); cursor: pointer;
  transition: background .15s ease, border-color .15s ease, transform .15s ease, box-shadow .2s ease;
}
button:hover:not(:disabled) { background: var(--surface-hover); border-color: var(--border-hover); }
button:active:not(:disabled) { transform: translateY(1px); }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
button:disabled { opacity: .45; cursor: not-allowed; }

button.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); font-weight: 600; }
button.primary:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover);
  box-shadow: 0 6px 22px rgba(var(--accent-rgb), .28); }
button.primary:active:not(:disabled) { background: var(--accent-strong); }

button.ghost { background: transparent; border-color: transparent; color: var(--text-secondary); }
button.ghost:hover:not(:disabled) { background: rgba(var(--accent-rgb), .08); color: var(--text); }
button.outline { background: transparent; border-color: var(--border-hover); }
button.outline:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
button.danger { background: rgba(var(--error-rgb), .14); border-color: rgba(var(--error-rgb), .4); color: var(--error); }
button.link { background: none; border: none; min-height: 0; padding: 0 2px; color: var(--accent); }
button.link:hover { text-decoration: underline; }
button.big { min-height: 50px; padding: 0 26px; font-size: 1.02rem; border-radius: 12px; }
```

### Cards
```css
.card, .panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 20px;
  transition: border-color .2s ease, transform .2s ease, box-shadow .2s ease;
}
.card.interactive:hover { border-color: var(--border-hover); transform: translateY(-2px); box-shadow: var(--shadow-2); }
.card.interactive:focus-within { border-color: var(--accent); }
.card.selected, .card[aria-selected="true"] { border-color: rgba(var(--accent-rgb), .6); box-shadow: 0 0 0 3px rgba(var(--accent-rgb), .12); }

/* Spotlight card (landing features): a gold glow follows the pointer */
.spotlight { position: relative; overflow: hidden; }
.spotlight::before { content: ""; position: absolute; inset: 0; opacity: 0; transition: opacity .3s ease; pointer-events: none;
  background: radial-gradient(340px circle at var(--mx, 50%) var(--my, 50%), rgba(var(--accent-rgb), .14), transparent 60%); }
.spotlight:hover::before { opacity: 1; }
```

### Navigation
```css
.topbar { position: sticky; top: 0; z-index: 20; height: 60px; display: flex; align-items: center; gap: 20px; padding: 0 24px;
  background: rgba(var(--bg-rgb), .72); backdrop-filter: blur(12px); border-bottom: 1px solid transparent;
  transition: border-color .2s ease, background .2s ease; }
.topbar.scrolled { background: rgba(var(--bg-rgb), .92); border-bottom-color: var(--border); }
.topbar nav button { background: none; border: none; color: var(--text-tertiary); font-weight: 500; position: relative; }
.topbar nav button:hover { color: var(--text); background: rgba(var(--accent-rgb), .06); }
.topbar nav button.active { color: var(--text); }
.topbar nav button.active::after { content: ""; position: absolute; left: 12px; right: 12px; bottom: -11px; height: 2px;
  border-radius: 2px; background: var(--accent); }
```

### Links
```css
a { color: var(--accent); text-decoration: none; background: linear-gradient(currentColor, currentColor) 0 100% / 0 1px no-repeat;
  transition: background-size .25s ease; }
a:hover { background-size: 100% 1px; }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
```

### Tags / Badges
```css
.tag { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 9px; border-radius: 999px;
  font: 600 .7rem/1 var(--font-body); letter-spacing: .02em; background: var(--surface-alt); color: var(--text-secondary);
  border: 1px solid var(--border); }
.tag.good  { background: rgba(var(--success-rgb), .12); color: var(--success); border-color: rgba(var(--success-rgb), .3); }
.tag.bad   { background: rgba(var(--error-rgb), .12);   color: var(--error);   border-color: rgba(var(--error-rgb), .3); }
.tag.warn  { background: rgba(var(--warning-rgb), .12); color: var(--warning); border-color: rgba(var(--warning-rgb), .3); }
.tag.gold  { background: rgba(var(--accent-rgb), .12);  color: var(--accent);  border-color: rgba(var(--accent-rgb), .35); }
```

### Inputs
```css
input, select, textarea { font: 400 .95rem var(--font-body); min-height: 42px; padding: 0 12px; border-radius: 10px;
  background: var(--bg-deep); color: var(--text); border: 1px solid var(--border); transition: border-color .15s, box-shadow .15s; }
input:hover, select:hover, textarea:hover { border-color: var(--border-hover); }
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(var(--accent-rgb), .18); }
input:disabled { opacity: .5; cursor: not-allowed; }
```

### Move-quality badges
Brilliant `!!` teal, Great `!` blue, Best `★` / Excellent green, Good muted green, Book `📖` bronze, Inaccuracy `?!` amber, Mistake `?` orange, Blunder `??` red. These are chess conventions players recognise and are allowed as fixed colours inside `.mq-*` only.

## 5. Layout Principles

**Container:**
- Max width: 1280px (app), 1180px (landing sections)
- Padding: 24px desktop, 16px mobile
- Narrow variant (forms, profile): 640px

**Spacing Scale (4px base):** 4, 8, 12, 16, 20, 24, 32, 48, 72, 112
- Landing section padding: 112px desktop / 72px mobile
- App page padding: 28px top, 24px sides
- Component gap: 16px; card internal padding: 20px (24px on landing)

**Grid:**
```css
.container { max-width: 1280px; margin: 0 auto; padding: 0 24px; }
.bento { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 16px; }
.bento .b-wide { grid-column: span 4; } .bento .b-tall { grid-row: span 2; } .bento > * { grid-column: span 2; }
.app-split { display: grid; grid-template-columns: minmax(280px, 360px) minmax(0, 1fr); gap: 20px; align-items: start; }
```

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat | border `--border`, no shadow | lists, table rows, inputs |
| Subtle (`--shadow-1`) | `0 1px 2px rgba(0,0,0,.4), 0 2px 8px rgba(0,0,0,.25)` | panels, cards at rest |
| Elevated (`--shadow-2`) | `0 10px 30px rgba(0,0,0,.45)` | hovered cards, dropdowns, boards |
| Floating (`--shadow-3`) | `0 24px 60px rgba(0,0,0,.55)` | hero board, auth card, modals |
| Glow | `0 0 0 1px rgba(var(--accent-rgb),.35), 0 8px 32px rgba(var(--accent-rgb),.18)` | featured card, primary CTA hover |

## 7. Animation & Interaction

**Motion Philosophy**: motion explains, it never decorates the work area. Only `opacity` and `transform`, 150–600 ms, ease-out `cubic-bezier(.2,.7,.2,1)`.
**Tier**: L2

### Dependencies
None: CSS keyframes + one IntersectionObserver hook (`useReveal`).

### Entrance Animation
```css
@keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
.enter { animation: rise .5s cubic-bezier(.2,.7,.2,1) backwards; }
.enter-2 { animation-delay: .08s; } .enter-3 { animation-delay: .16s; } .enter-4 { animation-delay: .24s; }
```
(Fill mode `backwards`, never `both`: a held transform breaks the board's dragged piece.)

### Scroll Behavior
```js
// useReveal: adds .in when 15% of the element is visible; once only.
const io = new IntersectionObserver((es) => es.forEach((e) => {
  if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
}), { threshold: 0.15 });
document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
```
```css
.reveal { opacity: 0; transform: translateY(24px); transition: opacity .6s ease, transform .6s cubic-bezier(.2,.7,.2,1); }
.reveal.in { opacity: 1; transform: none; }
.reveal[data-delay="1"] { transition-delay: .08s; } .reveal[data-delay="2"] { transition-delay: .16s; }
```
Nav gets `.scrolled` after 8px of scroll (passive listener).

### Hover & Focus States
Every interactive element has a hover (colour or lift) and a 2px gold `:focus-visible` outline. Cards lift 2px; buttons press 1px.

### Special Effects (the six signature moments, landing page)
1. **Hero H1 gradient text**: "Mind" in a gold gradient that drifts (`background-position` 8 s loop).
2. **Section H2 word reveal**: words rise in sequence when the heading scrolls into view (opacity + translate, 40 ms stagger).
3. **Body: typed eyebrow**: the hero tagline types itself once ("Your opening second").
4. **Element: magnetic CTA**: the main button follows the pointer by up to 6px (rAF throttled, hover devices only).
5. **Component: spotlight bento**: feature cards in an uneven bento grid with a gold glow tracking the pointer.
6. **Background: aurora**: three slow drifting radial gradients (navy, gold, blue) behind the hero; static on mobile and reduced motion.
- **Hook after the hero**: an endless marquee band of famous openings in large type.
- **The detail**: hover the brand knight and it hops one L-shaped knight move.

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important;
    transition-duration: .01ms !important; scroll-behavior: auto !important; }
  .reveal { opacity: 1; transform: none; }
  .aurora, .marquee-track { animation: none !important; }
}
```

## 8. Do's and Don'ts

### Do
- Use the token variables for every colour, radius and shadow.
- Keep gold for one primary action and the current selection per view.
- Give every page an obvious next step (a gold button) when it is empty.
- Align numbers with tabular figures; show moves in SAN with move numbers.
- Keep the board the visual centre of chess pages; panels sit beside it, never over it.
- Respect `prefers-reduced-motion` and keep 44×44px touch targets on phones.

### Don't
- ❌ Hard-coded hex colours in components (only `.mq-*` chess-convention badges are exempt).
- ❌ More than one gold element competing in the same view.
- ❌ `filter: blur()` on moving elements, or `backdrop-filter` above 14px.
- ❌ Animations held with `animation-fill-mode: both`/`forwards` on transforms around the board (breaks piece dragging).
- ❌ Neon glows, scanlines, glitch text, gamer fonts.
- ❌ Emoji as interface icons (inline SVG instead); the 📖 "book" move symbol is the only exception.
- ❌ Text below 12px or tertiary text for anything the user must read to act.
- ❌ Motion on the work area while the user is thinking (boards, move lists, forms).
- ❌ Solid grey placeholder boxes: use a real board position.

## 9. Responsive Behavior

**Breakpoints:**
| Name | Width | Key Changes |
|------|-------|-------------|
| Desktop | > 1100px | 3-column study view, bento 6 columns, hero side by side |
| Tablet | 761–1100px | study view 2 columns (tools below), bento 2 columns |
| Mobile | ≤ 760px | single column, nav in a drawer, hero stacked (board above copy), aurora static |

**Touch Targets:** minimum 44×44px on touch devices.
**Collapsing Strategy:** lists above details; the board stays full width; side panels follow it; tables become cards.

```css
@media (max-width: 1100px) { .bento { grid-template-columns: repeat(2, minmax(0, 1fr)); } .bento > * { grid-column: span 1; } .bento .b-wide { grid-column: span 2; } }
@media (max-width: 760px) {
  .container { padding: 0 16px; } .app-split { grid-template-columns: minmax(0, 1fr); }
  .bento { grid-template-columns: minmax(0, 1fr); } .bento > *, .bento .b-wide { grid-column: auto; }
  button, input, select { min-height: 44px; }
}
```
