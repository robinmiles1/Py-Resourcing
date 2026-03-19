# Changelog

All notable changes to Py Resourcing.

---

## [1.3] — 2026-03-19

### Added
- **BAU stat card** — new amber "BAU in Period" card on the dashboard showing distinct BAU items in the current period
- **CRQ # column** — added to the Allocations in Period table (after Type), showing CRQ number where set
- **Stat card table filtering** — clicking the "Projects in Period" or "BAU in Period" stat card now filters the Allocations in Period table to show only the relevant type; click again to clear
- **Settings modal** — gear icon in topbar opens a settings panel to view/copy/regenerate the `/api/stats` API key
- **`/api/settings/apikey`** — GET returns current key, POST regenerates it
- **`/api/stats`** — protected endpoint returning live daily stats: `active_resources`, `active_projects`, `BAU_requests`, `total_allocations_today`, `total_hours_today`, `available_resources`, `overloaded_resources`. Requires `X-API-Key` header or `?api_key=` query param

### Changed
- Heatmap filter (`applyHeatmapFilter`) now handles `'bau'` in addition to `'project'` and `'overloaded'`
- Donut chart in Workload Breakdown panel increased in size for better readability
- Period table "no allocations" empty state colspan corrected to 7

---

## [1.2] — 2026-03-18

### Added
- Heatmap stat card filters — clicking "Projects in Period" or "Overloaded in Period" highlights/dims heatmap cells
- Workload Breakdown panel with donut (Project vs BAU allocation count) and stacked bar chart (hours per resource)
- Team Synopsis panel with busiest/quietest day, most/least utilised resource, avg daily load
- CRQ number and Requestor fields on allocation form and edit modal; CRQ field hidden for BAU type
- Panel collapse state persisted to `localStorage`

### Changed
- Heatmap cell sizing adapts to container width and view (week/month/quarter)
- Today column highlighted with accent outline across all views

---

## [1.1] — earlier

### Added
- Week / Month / Quarter view selector with prev/next navigation
- Sticky resource name column in heatmap
- Edit and Delete actions on all allocations table
- Toast notifications for form actions

---

## [1.0] — initial

- Single-file Python resource/capacity management tool
- Heatmap dashboard, allocation form, SQLite persistence
- Zero mandatory dependencies
