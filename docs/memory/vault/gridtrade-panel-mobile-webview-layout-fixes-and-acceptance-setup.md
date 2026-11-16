---
title: 'Gridtrade panel: mobile WebView layout fixes and acceptance setup'
tags:
  - gridtrade
  - webview
  - layout
  - tailwind
  - lightweight-charts
  - android
created: '2026-11-16T13:58:50+08:00'
---

# Gridtrade panel: mobile WebView layout fixes and acceptance setup

Project: /Users/user/Dev/bnapi — FastAPI + React SPA quant panel, served from web/dist, packaged as a WebView APK at apk/gridtrade.apk (com.gridtrade.panel, minSdk 26, target 34).

Run: `.venv/bin/python -m gridtrade.api` (editable install, dep on PYTHONPATH no longer needed); tests `.venv/bin/python -m pytest` (52 pass, pyproject sets pythonpath=["src"]); web `cd web && pnpm build`.

Mobile WebView layout rules that mattered (360x800 CSS, font_scale 1.3, dpr 3):
- A min-content wider than the screen widens the layout viewport (416 vs 360), and `position: fixed` then anchors bottom nav off-screen. Global rule in web/src/index.css: `main :where(.grid) > * { min-width: 0; }` plus `setUseWideViewPort(true)` in MainActivity.
- Chrome UA stylesheet makes `<button>` a flex container with align-items:center, so inner rows do NOT stretch; give them `w-full` when using justify-between + truncate.
- WebView ignores backdrop-blur; all sticky/fixed surfaces must be opaque (header `bg-base`, nav `bg-[#0d1014]`).
- Row pattern for long label/value: `flex ... gap-3` + `min-w-0 truncate` on left + `shrink-0` on right.
- lightenweight-charts: `fitContent()` clips first/last time labels; use `setVisibleLogicalRange({from:-6,to:n+6})` and bump rightPriceScale scaleMargins top to ~0.18; hide the drawdown sub-chart's time axis and last-value tag.
- Dense monthly table: `.monthly-table :is(th,td){padding:0 8px;white-space:nowrap}` with overflow-x-auto wrapper (462px table in 286px card, document width stays 360).
- Verification is DOM/AX based (CDP probes): all 9 hash routes report scrollWidth==clientWidth==360, fixed nav bottom 710, no out-of-viewport elements.

Backend: /api/* Bearer or gt_token cookie; token in var/token (0600); stale queued/running runs are marked failed on boot when GRIDTRADE_AUTORUN=1 (store.fail_interrupted).
