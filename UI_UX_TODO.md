# UI/UX TODO — Resume AI Frontend

> All items must be **100% mobile-responsive and friendly**.

## High Priority

- [x] **1. Mobile-responsive Navbar** — Hamburger menu on small screens, proper touch targets
- [x] **2. Dark mode toggle** — Tailwind dark mode with Navbar toggle, persist preference
- [x] **3. Toast notifications** — Global toast system replacing inline error banners
- [x] **4. Delete analysis** — Trash icon on HistoryPage with confirmation modal
- [x] **5. PDF export of results** — Download a formatted report of ATS results
- [x] **6. Mobile polish pass** — Touch-friendly form inputs, proper spacing, no overflow

## Medium Priority

- [x] **7. Copy-to-clipboard on rewritten bullets** — Copy button per bullet point
- [x] **8. Skeleton loaders** — Replace spinner with layout-shaped placeholders
- [x] **9. Search & filter on HistoryPage** — Search by role/company, filter by score, sort
- [x] **10. Form validation UX** — Character counts, inline field errors, URL validation
- [x] **11. Component extraction** — Move ScoreGauge, ScoreBar, etc. to components/
- [x] **12. Optimistic analysis card** — Show "processing" entry in history immediately

## Lower Priority / Nice-to-Have

- [x] **13. Confetti on high score** — Celebration animation when ats_score ≥ 85
- [x] **14. Comparison view** — Side-by-side compare of two analyses
- [x] **15. PWA support** — manifest.json + service worker for installability
- [x] **16. Analytics dashboard** — Score trends, common keyword gaps over time
- [ ] **17. Shareable results link** — Public read-only URL for an analysis *(needs backend)*
- [ ] **18. i18n / localization** — react-i18next setup *(deferred)*
- [x] **19. Accessibility audit** — aria attributes, keyboard nav, focus management
- [x] **20. Frontend unit tests** — Vitest + React Testing Library (20 tests)
- [x] **21. Auth loading gate** — Prevent login page flash during token refresh
