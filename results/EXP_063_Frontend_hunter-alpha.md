Looking at your codebase, the dashboard is Tailwind-based with inline utility classes. The cleanest approach is a CSS custom properties layer that redefines Tailwind colors on a `[data-theme="light"]` scope — no need to rewrite every HTML class.

Here's the complete design system addition:

---

## 1. Add to `static/styles.css`

Create this file (or append to an existing stylesheet):

```css
/* ═══════════════════════════════════════════════════════════════════
   PolySINT Design System — Theme Engine
   ═══════════════════════════════════════════════════════════════════ */

/* ─── Base: Dark Mode (default) ────────────────────────────────── */
:root {
  --bg-primary: #080c14;
  --bg-surface: #0f1724;
  --bg-elevated: #151f30;
  --bg-hover: rgba(16, 230, 160, 0.04);

  --border-subtle: rgba(255, 255, 255, 0.06);
  --border-medium: rgba(255, 255, 255, 0.10);
  --border-accent: rgba(16, 230, 160, 0.25);

  --text-primary: #e8ece4;
  --text-secondary: #94a3b8;
  --text-muted: #4b5870;
  --text-inverse: #0a0e18;

  --accent: #10e6a0;
  --accent-dim: rgba(16, 230, 160, 0.12);
  --accent-hover: #34f0b8;

  --danger: #f87171;
  --danger-dim: rgba(248, 113, 113, 0.12);
  --warning: #fbbf24;
  --warning-dim: rgba(251, 191, 36, 0.12);
  --info: #60a5fa;
  --info-dim: rgba(96, 165, 250, 0.12);

  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.5);
  --shadow-lg: 0 12px 40px rgba(0, 0, 0, 0.6);

  --toggle-bg: #151f30;
  --toggle-track: rgba(255, 255, 255, 0.08);
  --toggle-knob: #10e6a0;
  --toggle-icon-sun: rgba(255, 255, 255, 0.2);
  --toggle-icon-moon: rgba(255, 255, 255, 0.9);

  --modal-overlay: rgba(0, 0, 0, 0.7);
}

/* ─── Light Mode ───────────────────────────────────────────────── */
[data-theme="light"] {
  --bg-primary: #f3f1ec;
  --bg-surface: #ffffff;
  --bg-elevated: #f8f6f1;
  --bg-hover: rgba(0, 80, 55, 0.03);

  --border-subtle: rgba(0, 0, 0, 0.06);
  --border-medium: rgba(0, 0, 0, 0.10);
  --border-accent: rgba(0, 80, 55, 0.2);

  --text-primary: #1a1d26;
  --text-secondary: #5a6478;
  --text-muted: #9ba3b4;
  --text-inverse: #f3f1ec;

  --accent: #007a55;
  --accent-dim: rgba(0, 122, 85, 0.08);
  --accent-hover: #00996b;

  --danger: #dc2626;
  --danger-dim: rgba(220, 38, 38, 0.08);
  --warning: #d97706;
  --warning-dim: rgba(217, 119, 6, 0.08);
  --info: #2563eb;
  --info-dim: rgba(37, 99, 235, 0.08);

  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.08);
  --shadow-lg: 0 12px 40px rgba(0, 0, 0, 0.10);

  --toggle-bg: #e8e5de;
  --toggle-track: rgba(0, 0, 0, 0.06);
  --toggle-knob: #007a55;
  --toggle-icon-sun: rgba(0, 0, 0, 0.7);
  --toggle-icon-moon: rgba(0, 0, 0, 0.15);

  --modal-overlay: rgba(0, 0, 0, 0.3);
}

/* ─── Smooth Transition on Theme Switch ────────────────────────── */
body,
body *::before,
body *::after {
  transition: background-color 0.35s ease,
              color 0.35s ease,
              border-color 0.35s ease,
              box-shadow 0.35s ease,
              fill 0.35s ease;
}

/* Reduce motion for users who prefer it */
@media (prefers-reduced-motion: reduce) {
  body,
  body *::before,
  body *::after {
    transition: none !important;
  }
}

/* ─── Override Tailwind Colors via Custom Properties ──────────────
   These rules remap your existing Tailwind utility classes so you
   don't have to rewrite every HTML element. */

[data-theme="light"] .bg-gray-900 { background-color: var(--bg-surface) !important; }
[data-theme="light"] .bg-gray-800 { background-color: var(--bg-elevated) !important; }
[data-theme="light"] .bg-gray-700\/30 { background-color: var(--bg-hover) !important; }
[data-theme="light"] .bg-gray-700\/50 { background-color: var(--bg-hover) !important; }

[data-theme="light"] .text-gray-200 { color: var(--text-primary) !important; }
[data-theme="light"] .text-gray-300 { color: var(--text-primary) !important; }
[data-theme="light"] .text-gray-400 { color: var(--text-secondary) !important; }
[data-theme="light"] .text-gray-500 { color: var(--text-muted) !important; }
[data-theme="light"] .text-gray-600 { color: var(--text-muted) !important; }

[data-theme="light"] .border-gray-700 { border-color: var(--border-medium) !important; }
[data-theme="light"] .border-gray-700\/50 { border-color: var(--border-subtle) !important; }
[data-theme="light"] .border-gray-600 { border-color: var(--border-medium) !important; }
[data-theme="light"] .border-gray-800 { border-color: var(--border-subtle) !important; }

/* Accent class remapping */
[data-theme="light"] .bg-polysint { background-color: var(--accent) !important; }
[data-theme="light"] .text-polysint { color: var(--accent) !important; }
[data-theme="light"] .border-polysint\/30 { border-color: var(--border-accent) !important; }

/* Danger states */
[data-theme="light"] .text-red-400 { color: var(--danger) !important; }
[data-theme="light"] .bg-red-500\/5 { background-color: var(--danger-dim) !important; }
[data-theme="light"] .bg-red-500\/10 { background-color: var(--danger-dim) !important; }
[data-theme="light"] .bg-red-500\/20 { background-color: var(--danger-dim) !important; }
[data-theme="light"] .bg-red-900\/20 { background-color: var(--danger-dim) !important; }
[data-theme="light"] .bg-red-900\/30 { background-color: var(--danger-dim) !important; }
[data-theme="light"] .border-red-500\/40 { border-color: var(--danger) !important; }
[data-theme="light"] .border-red-800 { border-color: var(--danger) !important; }

/* Warning states */
[data-theme="light"] .text-amber-400 { color: var(--warning) !important; }
[data-theme="light"] .bg-amber-500\/20 { background-color: var(--warning-dim) !important; }
[data-theme="light"] .border-amber-500\/40 { border-color: var(--warning) !important; }
[data-theme="light"] .border-amber-800 { border-color: var(--warning) !important; }

/* Info states */
[data-theme="light"] .text-blue-400 { color: var(--info) !important; }
[data-theme="light"] .bg-blue-900\/40 { background-color: var(--info-dim) !important; }
[data-theme="light"] .border-blue-800 { border-color: var(--info) !important; }

/* Emerald overrides */
[data-theme="light"] .text-emerald-400 { color: var(--accent) !important; }
[data-theme="light"] .bg-emerald-900\/40 { background-color: var(--accent-dim) !important; }
[data-theme="light"] .border-emerald-800\/50 { border-color: var(--border-accent) !important; }

/* Shadows */
[data-theme="light"] .shadow-lg { box-shadow: var(--shadow-lg) !important; }
[data-theme="light"] .shadow-sm { box-shadow: var(--shadow-sm) !important; }

/* ─── Theme Toggle Component ───────────────────────────────────── */
.theme-toggle {
  position: relative;
  width: 56px;
  height: 28px;
  border-radius: 14px;
  background: var(--toggle-bg);
  border: 1px solid var(--border-medium);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 6px;
  flex-shrink: 0;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.theme-toggle:hover {
  border-color: var(--border-accent);
}

.theme-toggle__icon {
  width: 14px;
  height: 14px;
  z-index: 1;
  transition: opacity 0.3s ease;
}

.theme-toggle__sun {
  color: var(--toggle-icon-sun);
}

.theme-toggle__moon {
  color: var(--toggle-icon-moon);
}

.theme-toggle__knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--toggle-knob);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  transition: transform 0.35s cubic-bezier(0.68, -0.55, 0.265, 1.55);
}

[data-theme="light"] .theme-toggle__knob {
  transform: translateX(28px);
}

/* ─── Body / Page-Level Theming ────────────────────────────────── */
body {
  background-color: var(--bg-primary);
  color: var(--text-primary);
}

/* Modal overlay */
#aiModal {
  background-color: var(--modal-overlay);
}
```

---

## 2. Theme Toggle Button — HTML

Add this into your `index.html` toolbar/header area, wherever the research toggle lives:

```html
<!-- Theme Toggle -->
<button class="theme-toggle" onclick="toggleTheme()" title="Toggle dark / light mode" aria-label="Toggle theme">
  <!-- Sun icon (visible in light mode) -->
  <svg class="theme-toggle__icon theme-toggle__sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <circle cx="12" cy="12" r="5"/>
    <line x1="12" y1="1" x2="12" y2="3"/>
    <line x1="12" y1="21" x2="12" y2="23"/>
    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
    <line x1="1" y1="12" x2="3" y2="12"/>
    <line x1="21" y1="12" x2="23" y2="12"/>
    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
  </svg>
  <!-- Sliding knob -->
  <div class="theme-toggle__knob"></div>
  <!-- Moon icon (visible in dark mode) -->
  <svg class="theme-toggle__icon theme-toggle__moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
  </svg>
</button>
```

---

## 3. Add to `static/app.js`

Append these functions to your existing JS:

```javascript
// ─── Theme Toggle ────────────────────────────────────────────────
function initTheme() {
    const saved = localStorage.getItem('polysint_theme');
    if (saved === 'light' || saved === 'dark') {
        document.documentElement.setAttribute('data-theme', saved);
    } else {
        // Respect OS preference on first visit
        const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
        document.documentElement.setAttribute('data-theme', prefersLight ? 'light' : 'dark');
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('polysint_theme', next);
}

// Call initTheme early — before DOM paints
initTheme();
```

Add `initTheme()` call to the top of your `DOMContentLoaded` listener (it's fine to call it before too — `documentElement` is always available):

```javascript
document.addEventListener("DOMContentLoaded", () => {
    initTheme();      // ← add this
    loadWatchlist();
    initResearchToggle();
    // ... rest unchanged
});
```

---

## How It Works

| Layer | Mechanism |
|---|---|
| **Color tokens** | CSS custom properties on `:root` (dark defaults) and `[data-theme="light"]` (light overrides) |
| **Tailwind override** | Scoped selectors like `[data-theme="light"] .text-gray-400` remap existing utility classes — your HTML stays untouched |
| **Toggle** | Sets `data-theme` on `<html>`, persists to `localStorage` |
| **OS respect** | `prefers-color-scheme` is the fallback on first visit |
| **Motion** | All color/background/border changes animate over 350ms; respects `prefers-reduced-motion` |

The light palette is deliberately warm-off-white (`#f3f1ec`) rather than sterile white, and the accent shifts from bright teal to a deeper forest green — so both modes feel intentional rather than just "inverted."
