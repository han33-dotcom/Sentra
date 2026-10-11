# Sentra: workforce readiness site (FYP)

Scroll-driven 3D marketing site. The camera zooms out step by step:
**device → person → data → team → institution**, then comes back to the band for the pilot request.

"Sentra" is a placeholder brand. The band, worker, site maps and dashboard are all built in code.
No device-maker names, logos or product designs are used.

## Run it

Double-click `index.html`. All libraries are in `vendor/`, so it works offline from disk.
(Fonts load from Google Fonts when online; system fonts are used otherwise.)

To share on a phone over Wi-Fi: `python -m http.server 8080` in this folder, then open
`http://<your-PC-IP>:8080`.

Useful URL flags:
- `?static=1` forces the static fallback (no WebGL), to preview what low-end phones get.
- `?static=0` forces the 3D version, even on a device the detector thinks is low-end.

## Files

| File | What it does |
|---|---|
| `index.html` | All copy and the 14 scroll sections. Each `<section>` has `data-pose` (camera/scene), `data-screen` (what the band shows), `data-scale` (zoom rail) and `data-time` (nav shift clock). |
| `css/styles.css` | Design tokens (light + dark) at the top. The 3D scene reads the same tokens. |
| `js/main.js` | Three.js scene (band, worker, data streams, baseline, site maps, crew, data-residency dome), poses, band screen modes, Lenis + GSAP on one clock, form. |
| `js/charts.js` | The small live charts (baseline, readiness, exertion, lone-worker, trends, wear, dashboard). All data there is illustrative. |
| `vendor/` | three r128, GSAP 3.12.5 + ScrollTrigger, Lenis 1.1.13. |

## Editing

- **Copy:** edit `index.html` directly.
- **Camera per section:** `POSES` in `js/main.js` (`d` = distance, `yaw`/`pitch` = angle, `wk` = worker opacity, `sf` = data streams, `bl` = baseline, `crew`/`sites`/`dome` = zoomed-out layers). Phone overrides sit right below it.
- **Band screen:** `SCREENS` in `js/main.js`, one function per mode.
- **Colours:** tokens at the top of `css/styles.css`.

## Before going live

- The pilot form validates on the page but does not send anywhere yet. See the `TODO` in `js/main.js` (Formspree, EmailJS or our API).
- All numbers on the page are labelled "illustrative" or "pilot targets". Keep it that way until a pilot produces results.
- Wording rules: fitness-for-shift, wellness signal, flag for check-in. No diagnosis, no medical-grade claims, no fall detection, SpO2, ECG or heat-stress claims. Footer states it is not a medical device.

## Behaviour notes

- Smooth scroll: Lenis, ScrollTrigger and the render loop share `gsap.ticker`. Scroll sets a target pose from the live layout; each frame damps toward it (distance interpolated in log space so the 5 m → 2 km zoom feels even).
- `prefers-reduced-motion`: no smooth scroll, no damping, no idle sway.
- Static fallback: no WebGL, ≤3 CPU cores, ≤2 GB memory, Save-Data on, or a phone that can't hold frame rate in its first 4 seconds.
