#!/usr/bin/env python3

"""
Py Resourcing — Team Resource & Capacity Management (Single-File Edition)
Provides a heatmap dashboard and allocation request form for managing team capacity.

Usage:
    python3 pyresourcing.py                 # Start on port 8460
    python3 pyresourcing.py --port 9000     # Custom port

Zero mandatory dependencies — stdlib only.
"""

import json
import os
import sys
import sqlite3
import threading
import uuid
import logging
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


# ======================================================================
# Constants
# ======================================================================

DEFAULT_PORT = 8460
BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "pyresourcing.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("pyresourcing")


# ======================================================================
# Database Layer
# ======================================================================

class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    @property
    def conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        c = sqlite3.connect(str(self.db_path))
        c.executescript("""
            CREATE TABLE IF NOT EXISTS allocations (
                id            TEXT PRIMARY KEY,
                resource      TEXT NOT NULL,
                type          TEXT NOT NULL,
                name          TEXT NOT NULL,
                start_date    TEXT NOT NULL,
                end_date      TEXT NOT NULL,
                hours_per_day REAL NOT NULL DEFAULT 1.0,
                created_at    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alloc_resource ON allocations(resource);
            CREATE INDEX IF NOT EXISTS idx_alloc_dates    ON allocations(start_date, end_date);
        """)
        c.commit()
        self._migrate(c)
        c.close()

    def _migrate(self, c):
        """Add columns that may be missing from older database versions."""
        def has_column(table, column):
            cur = c.execute(f"PRAGMA table_info({table})")
            return any(row[1] == column for row in cur.fetchall())
        if not has_column("allocations", "crq_number"):
            c.execute("ALTER TABLE allocations ADD COLUMN crq_number TEXT NOT NULL DEFAULT ''")
        if not has_column("allocations", "requestor"):
            c.execute("ALTER TABLE allocations ADD COLUMN requestor TEXT NOT NULL DEFAULT ''")
        c.commit()

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def new_id(self, prefix=""):
        short = str(uuid.uuid4())[:8]
        return f"{prefix}{short}" if prefix else short


# ======================================================================
# HTML / SPA Builder
# ======================================================================

def build_app_html():
    return r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Py Resourcing — Team Capacity Manager</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
    --bg-primary: #080b10;
    --bg-secondary: #0c1018;
    --bg-card: #10151e;
    --bg-card-hover: #151c28;
    --bg-elevated: #1a2332;
    --bg-input: #0e1420;
    --border-subtle: rgba(56, 189, 248, 0.07);
    --border-active: rgba(56, 189, 248, 0.18);
    --border-focus: rgba(56, 189, 248, 0.5);
    --text-primary: #e2e8f0;
    --text-secondary: #8b99ad;
    --text-muted: #4a5568;
    --accent: #38bdf8;
    --accent-glow: rgba(56, 189, 248, 0.12);
    --accent-dim: rgba(56, 189, 248, 0.5);
    --success: #22c55e;
    --success-bg: rgba(34, 197, 94, 0.08);
    --warning: #f59e0b;
    --warning-bg: rgba(245, 158, 11, 0.08);
    --danger: #ef4444;
    --danger-bg: rgba(239, 68, 68, 0.08);
    --info: #8b5cf6;
    --info-bg: rgba(139, 92, 246, 0.08);
    --font-display: 'Outfit', sans-serif;
    --font-mono: 'JetBrains Mono', monospace;
    --radius: 10px;
    --radius-sm: 6px;
    --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font-display); background: var(--bg-primary); color: var(--text-primary); min-height: 100vh; }
body::before { content: ''; position: fixed; inset: 0; background: linear-gradient(rgba(56,189,248,0.015) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,0.015) 1px, transparent 1px); background-size: 50px 50px; pointer-events: none; z-index: 0; }

/* Topbar */
.topbar { position: sticky; top: 0; z-index: 100; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; height: 52px; background: rgba(8,11,16,0.9); backdrop-filter: blur(16px); border-bottom: 1px solid var(--border-subtle); }
.topbar-brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; letter-spacing: -0.02em; }
.topbar-brand svg { flex-shrink: 0; }
.topbar-brand span { color: var(--accent); }
.topbar-nav { display: flex; gap: 2px; }
.nav-btn { padding: 8px 16px; font-size: 12px; font-weight: 600; color: var(--text-muted); background: none; border: none; cursor: pointer; border-bottom: 2px solid transparent; transition: var(--transition); font-family: var(--font-display); text-transform: uppercase; letter-spacing: 0.06em; }
.nav-btn:hover { color: var(--text-secondary); }
.nav-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
.topbar-status { display: flex; align-items: center; gap: 14px; font-size: 11px; font-family: var(--font-mono); color: var(--text-secondary); }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); box-shadow: 0 0 8px var(--success); animation: pulse-dot 2s ease infinite; }
@keyframes pulse-dot { 0%,100%{opacity:1} 50%{opacity:0.4} }

/* Pages */
.page { display: none; width: 100%; padding: 20px 32px 60px; position: relative; z-index: 1; }
.page.active { display: block; }

/* Stat cards */
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 20px; }
.stat-card { background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius); padding: 16px 18px; transition: var(--transition); position: relative; overflow: hidden; }
.stat-card:hover { border-color: var(--border-active); background: var(--bg-card-hover); }
.stat-card::after { content:''; position:absolute; top:0; left:0; right:0; height:2px; }
.stat-card.a-blue::after   { background: linear-gradient(90deg, var(--accent), transparent); }
.stat-card.a-green::after  { background: linear-gradient(90deg, var(--success), transparent); }
.stat-card.a-red::after    { background: linear-gradient(90deg, var(--danger), transparent); }
.stat-card.a-purple::after { background: linear-gradient(90deg, var(--info), transparent); }
.stat-card.a-amber::after  { background: linear-gradient(90deg, var(--warning), transparent); }
.stat-label { font-size: 10.5px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 6px; }
.stat-value { font-size: 26px; font-weight: 700; letter-spacing: -0.03em; font-family: var(--font-mono); }
.stat-value.blue   { color: var(--accent); }
.stat-value.green  { color: var(--success); }
.stat-value.red    { color: var(--danger); }
.stat-value.purple { color: var(--info); }
.stat-value.amber  { color: var(--warning); }
.stat-sub { font-size: 10.5px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 3px; }

/* Panel */
.panel { background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius); overflow: hidden; transition: var(--transition); margin-bottom: 16px; }
.panel:hover { border-color: var(--border-active); }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border-subtle); }
.panel-title { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); display: flex; align-items: center; gap: 8px; }
.panel-badge { font-family: var(--font-mono); font-size: 10px; padding: 2px 8px; border-radius: 99px; background: var(--accent-glow); color: var(--accent); }
.panel-body { padding: 12px 16px; }
.panel-header { cursor: pointer; user-select: none; }
.panel-chevron { font-size: 10px; color: var(--text-muted); transition: transform 0.2s; display: inline-block; margin-left: 6px; vertical-align: middle; opacity: 0.6; }
.panel.collapsed .panel-chevron { transform: rotate(-90deg); }
.panel.collapsed > *:not(.panel-header) { display: none !important; }

/* Data table */
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th { text-align: left; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); padding: 8px 10px; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
.data-table td { padding: 8px 10px; border-bottom: 1px solid rgba(56,189,248,0.03); font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.data-table tr:hover td { background: rgba(56,189,248,0.02); }
.fname { color: var(--text-primary) !important; font-weight: 500 !important; }

/* Pill */
.pill { display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 99px; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }

/* Buttons */
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border: 1px solid var(--border-active); border-radius: var(--radius-sm); background: var(--bg-elevated); color: var(--accent); font-family: var(--font-mono); font-size: 11px; font-weight: 500; cursor: pointer; transition: var(--transition); }
.btn:hover { background: var(--accent-glow); border-color: var(--accent); }
.btn-sm { padding: 4px 10px; font-size: 10px; }
.btn-danger { border-color: rgba(239,68,68,0.3); color: var(--danger); }
.btn-danger:hover { background: var(--danger-bg); border-color: var(--danger); }
.btn-primary { background: var(--accent); color: var(--bg-primary); border-color: var(--accent); font-weight: 600; }
.btn-primary:hover { background: #5bcefa; }

/* Form */
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-grid .full { grid-column: 1 / -1; }
.form-group { display: flex; flex-direction: column; gap: 5px; }
.form-label { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); }
.form-input, .form-select { padding: 8px 12px; background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); color: var(--text-primary); font-family: var(--font-mono); font-size: 12px; transition: var(--transition); outline: none; width: 100%; }
.form-input:focus, .form-select:focus { border-color: var(--border-focus); }
.form-select { cursor: pointer; }

/* Tab bar */
.tab-bar { display: flex; gap: 2px; padding: 0 16px; background: var(--bg-card); border-bottom: 1px solid var(--border-subtle); }
.tab-btn { padding: 9px 14px; font-size: 11px; font-weight: 600; color: var(--text-muted); background: none; border: none; cursor: pointer; border-bottom: 2px solid transparent; transition: var(--transition); font-family: var(--font-display); text-transform: uppercase; letter-spacing: 0.06em; }
.tab-btn:hover { color: var(--text-secondary); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

/* Toasts */
.toast-container { position: fixed; top: 60px; right: 20px; z-index: 300; display: flex; flex-direction: column; gap: 8px; }
.toast { padding: 10px 16px; border-radius: var(--radius-sm); font-size: 12px; font-family: var(--font-mono); animation: slideIn 0.3s ease; min-width: 250px; max-width: 400px; }
.toast.success { background: var(--success-bg); border: 1px solid rgba(34,197,94,0.3); color: var(--success); }
.toast.error   { background: var(--danger-bg);  border: 1px solid rgba(239,68,68,0.3);  color: var(--danger); }
.toast.info    { background: var(--accent-glow); border: 1px solid var(--border-active); color: var(--accent); }
.toast.warning { background: var(--warning-bg); border: 1px solid rgba(245,158,11,0.3); color: var(--warning); }
@keyframes slideIn { from { opacity:0; transform: translateX(40px); } to { opacity:1; transform: translateX(0); } }
@keyframes fadeIn  { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
.anim { animation: fadeIn 0.35s ease both; }
.d1{animation-delay:.04s}.d2{animation-delay:.08s}.d3{animation-delay:.12s}.d4{animation-delay:.16s}

/* Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-active); border-radius: 3px; }

/* Modal */
.modal-overlay { display: none; position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); align-items: flex-start; justify-content: center; padding-top: 80px; }
.modal-overlay.open { display: flex; }
.modal { background: var(--bg-secondary); border: 1px solid var(--border-active); border-radius: var(--radius); width: 620px; max-width: calc(100vw - 40px); max-height: 85vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.5); }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--border-subtle); }
.modal-head h3 { font-size: 15px; font-weight: 700; }
.modal-close { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 18px; padding: 4px 8px; transition: var(--transition); }
.modal-close:hover { color: var(--text-primary); }
.modal-body { padding: 20px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid var(--border-subtle); }

/* Heatmap */
.heatmap-wrap { overflow-x: auto; padding-bottom: 4px; }
.heatmap-table { border-collapse: separate; border-spacing: 2px; font-size: 11px; }
.heatmap-label { font-family: var(--font-mono); font-size: 10px; color: var(--text-secondary); text-align: right; padding-right: 10px; white-space: nowrap; width: 120px; min-width: 120px; font-weight: 500; position: sticky; left: 0; background: var(--bg-card); z-index: 2; border-right: 1px solid var(--border-subtle); }
.heatmap-cell { width: 28px; height: 28px; border-radius: 3px; cursor: pointer; transition: transform 0.1s ease, opacity 0.1s ease; position: relative; }
.heatmap-cell:hover { transform: scale(1.2); z-index: 10; }
.hm-empty  { background: rgba(56,189,248,0.04); border: 1px solid rgba(56,189,248,0.06); }
.hm-low    { background: rgba(56,189,248,0.72); }
.hm-green  { background: rgba(34,197,94,0.72); }
.hm-amber  { background: rgba(245,158,11,0.72); }
.hm-over   { background: rgba(239,68,68,0.72); }
.hm-date-header { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); writing-mode: vertical-rl; text-orientation: mixed; padding: 4px 2px; white-space: nowrap; display: inline-block; }
.hm-weekend { opacity: 0.4; }
.hm-today-col .heatmap-cell { outline: 1px solid var(--accent-dim); outline-offset: 1px; }
.hm-today-col .hm-date-header { color: var(--accent); }
.hm-highlight { box-shadow: 0 0 0 2px rgba(56,189,248,0.9) !important; opacity: 1 !important; z-index: 5; }
.hm-dimmed { opacity: 0.1 !important; }
.stat-card.clickable-filter { cursor: pointer; }
.stat-card.filter-active { border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent); }
.hm-tooltip { position: fixed; z-index: 400; background: var(--bg-elevated); border: 1px solid var(--border-active); border-radius: var(--radius-sm); padding: 10px 14px; font-size: 11px; font-family: var(--font-mono); color: var(--text-primary); pointer-events: none; max-width: 240px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }

/* Legend */
.hm-legend { display: flex; align-items: center; gap: 10px; font-size: 10px; font-family: var(--font-mono); color: var(--text-muted); }
.hm-legend-cell { width: 14px; height: 14px; border-radius: 2px; display: inline-block; }

@media (max-width: 900px) {
    .form-grid { grid-template-columns: 1fr; }
    .stats-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
</head>
<body>

<div class="topbar">
    <div class="topbar-brand">
        <svg width="24" height="24" viewBox="0 0 26 26" fill="none">
            <rect x="1" y="1" width="24" height="24" rx="6" stroke="#38bdf8" stroke-width="1.5" fill="none"/>
            <circle cx="9" cy="10" r="2.5" stroke="#38bdf8" stroke-width="1.4" fill="none"/>
            <circle cx="17" cy="10" r="2.5" stroke="#38bdf8" stroke-width="1.4" fill="none"/>
            <path d="M5 19c0-2.2 1.8-4 4-4h8c2.2 0 4 1.8 4 4" stroke="#22c55e" stroke-width="1.4" stroke-linecap="round" fill="none"/>
        </svg>
        <span>Py</span>Resourcing
    </div>
    <div class="topbar-nav">
        <button class="nav-btn active" data-page="dashboard">Dashboard</button>
        <button class="nav-btn" data-page="requests">Resource Requests</button>
    </div>
    <div class="topbar-status">
        <div style="display:flex;align-items:center;gap:6px"><div class="status-dot"></div><span>ONLINE</span></div>
        <span id="clock"></span>
    </div>
</div>

<div class="toast-container" id="toasts"></div>
<div id="hm-tooltip" class="hm-tooltip" style="display:none"></div>

<!-- ====== DASHBOARD PAGE ====== -->
<div class="page active" id="page-dashboard">
    <div class="stats-row" id="stats-row"></div>

    <div class="panel anim d1" id="panel-heatmap">
        <div class="panel-header" onclick="togglePanel(this.closest('.panel'))">
            <div class="panel-title">Allocation Heatmap <span class="panel-chevron">▾</span></div>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap" onclick="event.stopPropagation()">
                <div style="display:flex;gap:0" class="tab-bar" id="view-tabs" style="border:none;padding:0;background:none;border-bottom:none">
                    <button class="tab-btn" data-view="week">Week</button>
                    <button class="tab-btn active" data-view="month">Month</button>
                    <button class="tab-btn" data-view="quarter">Quarter</button>
                </div>
                <button class="btn btn-sm" id="btn-prev">&#8249;</button>
                <span id="period-label" style="font-family:var(--font-mono);font-size:11px;color:var(--accent);min-width:160px;text-align:center"></span>
                <button class="btn btn-sm" id="btn-next">&#8250;</button>
            </div>
        </div>
        <div class="panel-body heatmap-wrap">
            <div id="heatmap-container" style="min-height:80px;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:12px;font-family:var(--font-mono)">Loading…</div>
        </div>
        <div style="padding:8px 16px 12px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">
            <div class="hm-legend">
                <span class="hm-legend-cell hm-empty"></span> Free
                <span class="hm-legend-cell hm-low" style="margin-left:6px"></span> &le;4h
                <span class="hm-legend-cell hm-green" style="margin-left:6px"></span> 4–6h
                <span class="hm-legend-cell hm-amber" style="margin-left:6px"></span> 6–7.4h
                <span class="hm-legend-cell hm-over" style="margin-left:6px"></span> &gt;7.4h (overloaded)
            </div>
        </div>
    </div>

    <div class="panel anim d2" id="synopsis-panel" style="display:none">
        <div class="panel-header" onclick="togglePanel(this.closest('.panel'))">
            <div class="panel-title">Team Synopsis <span class="panel-chevron">▾</span></div>
            <span id="synopsis-period-label" style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted)"></span>
        </div>
        <div class="panel-body" id="synopsis-body" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px"></div>
    </div>

    <div class="panel anim" id="charts-panel" style="display:none">
        <div class="panel-header" onclick="togglePanel(this.closest('.panel'))">
            <div class="panel-title">Workload Breakdown <span class="panel-chevron">▾</span></div>
            <span id="charts-period-label" style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted)"></span>
        </div>
        <div class="panel-body" style="display:flex;justify-content:center;gap:56px;flex-wrap:wrap;align-items:flex-start;padding:20px 24px">
            <div style="flex:0 1 280px">
                <div style="font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:16px;text-align:center">Project vs BAU — Allocation Count</div>
                <div id="chart-donut" style="display:flex;align-items:center;justify-content:center;gap:32px"></div>
            </div>
            <div style="flex:0 1 480px">
                <div style="font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:16px;text-align:center">Hours by Resource — Project vs BAU</div>
                <div id="chart-bars" style="overflow-x:auto;display:flex;justify-content:center"></div>
            </div>
        </div>
    </div>

    <div class="panel anim d3" id="panel-period-allocs">
        <div class="panel-header" onclick="togglePanel(this.closest('.panel'))">
            <div class="panel-title">Allocations in Period <span class="panel-chevron">▾</span></div>
            <span class="panel-badge" id="period-alloc-count">—</span>
        </div>
        <div class="panel-body" style="padding:0;overflow-x:auto">
            <table class="data-table">
                <thead><tr>
                    <th>Resource</th>
                    <th>Type</th>
                    <th>Name</th>
                    <th>Start</th>
                    <th>End</th>
                    <th>Hrs/Day</th>
                </tr></thead>
                <tbody id="period-alloc-body"></tbody>
            </table>
        </div>
    </div>
</div>

<!-- ====== RESOURCE REQUESTS PAGE ====== -->
<div class="page" id="page-requests">
    <div class="panel anim d1" id="panel-new-alloc">
        <div class="panel-header" onclick="togglePanel(this.closest('.panel'))">
            <div class="panel-title">New Allocation Request <span class="panel-chevron">▾</span></div>
        </div>
        <div class="panel-body">
            <form class="form-grid" id="alloc-form" onsubmit="submitAlloc(event)">
                <div class="form-group">
                    <label class="form-label">Resource</label>
                    <input class="form-input" id="f-resource" type="text" placeholder="Person name" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Type</label>
                    <select class="form-select" id="f-type" required onchange="toggleCrqField('f-crq-group', this.value)">
                        <option value="">— Select type —</option>
                        <option value="Project">Project</option>
                        <option value="BAU">BAU</option>
                    </select>
                </div>
                <div class="form-group" id="f-crq-group" style="display:none">
                    <label class="form-label">CRQ # <span style="color:var(--text-muted);font-size:0.8em">(if applicable)</span></label>
                    <input class="form-input" id="f-crq" type="text" placeholder="e.g. CRQ123456">
                </div>
                <div class="form-group">
                    <label class="form-label">Requestor</label>
                    <input class="form-input" id="f-requestor" type="text" placeholder="Requestor name">
                </div>
                <div class="form-group full">
                    <label class="form-label">Name</label>
                    <input class="form-input" id="f-name" type="text" placeholder="Project / task name" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Start Date</label>
                    <input class="form-input" id="f-start" type="date" required>
                </div>
                <div class="form-group">
                    <label class="form-label">End Date</label>
                    <input class="form-input" id="f-end" type="date" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Estimated Hours per Day</label>
                    <input class="form-input" id="f-hours" type="number" min="0.1" max="24" step="0.1" value="7.4" required>
                </div>
                <div class="form-group" style="align-self:flex-end">
                    <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">+ Add Allocation</button>
                </div>
            </form>
        </div>
    </div>

    <div class="panel anim d2" id="panel-all-allocs">
        <div class="panel-header" onclick="togglePanel(this.closest('.panel'))">
            <div class="panel-title">All Allocations <span class="panel-chevron">▾</span></div>
            <span class="panel-badge" id="alloc-count">—</span>
        </div>
        <div class="panel-body" style="padding:0;overflow-x:auto">
            <table class="data-table">
                <thead><tr>
                    <th>Resource</th>
                    <th>Type</th>
                    <th>Name</th>
                    <th>CRQ #</th>
                    <th>Requestor</th>
                    <th>Start</th>
                    <th>End</th>
                    <th>Hrs/Day</th>
                    <th>Created</th>
                    <th></th>
                </tr></thead>
                <tbody id="alloc-body"></tbody>
            </table>
        </div>
    </div>
</div>

<!-- ====== EDIT MODAL ====== -->
<div class="modal-overlay" id="edit-modal">
    <div class="modal">
        <div class="modal-head">
            <h3>Edit Allocation</h3>
            <button class="modal-close" onclick="closeEditModal()">&#10005;</button>
        </div>
        <div class="modal-body">
            <form class="form-grid" id="edit-form" onsubmit="submitEdit(event)">
                <input type="hidden" id="e-id">
                <div class="form-group">
                    <label class="form-label">Resource</label>
                    <input class="form-input" id="e-resource" type="text" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Type</label>
                    <select class="form-select" id="e-type" required onchange="toggleCrqField('e-crq-group', this.value)">
                        <option value="Project">Project</option>
                        <option value="BAU">BAU</option>
                    </select>
                </div>
                <div class="form-group" id="e-crq-group" style="display:none">
                    <label class="form-label">CRQ # <span style="color:var(--text-muted);font-size:0.8em">(if applicable)</span></label>
                    <input class="form-input" id="e-crq" type="text" placeholder="e.g. CRQ123456">
                </div>
                <div class="form-group">
                    <label class="form-label">Requestor</label>
                    <input class="form-input" id="e-requestor" type="text">
                </div>
                <div class="form-group full">
                    <label class="form-label">Name</label>
                    <input class="form-input" id="e-name" type="text" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Start Date</label>
                    <input class="form-input" id="e-start" type="date" required>
                </div>
                <div class="form-group">
                    <label class="form-label">End Date</label>
                    <input class="form-input" id="e-end" type="date" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Hours per Day</label>
                    <input class="form-input" id="e-hours" type="number" min="0.1" max="24" step="0.1" required>
                </div>
            </form>
        </div>
        <div class="modal-foot">
            <button class="btn" onclick="closeEditModal()">Cancel</button>
            <button class="btn btn-primary" onclick="document.getElementById('edit-form').requestSubmit()">Save Changes</button>
        </div>
    </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────
let currentView          = 'month';
let periodOffset         = 0;
let activeHeatmapFilter  = null;
let _projectCells        = new Set();
let _overloadedCells     = new Set();
const TODAY_STR  = new Date().toISOString().slice(0, 10);

// ── Utilities ────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
    const c = document.getElementById('toasts');
    const t = document.createElement('div');
    t.className = 'toast ' + type;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.remove(), 5000);
}

async function api(url, opts) {
    try {
        const r = await fetch(url, opts);
        return await r.json();
    } catch (e) {
        console.error(e);
        return null;
    }
}

function escHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function fmtDate(d) {
    const pad = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

// ── User identity (localStorage) ─────────────────────────────────────────
function getUsername() {
    let u = localStorage.getItem('py_resourcing_user');
    if (!u) {
        u = prompt('Enter your name — this will pre-fill the Resource field:') || '';
        if (u) localStorage.setItem('py_resourcing_user', u);
    }
    return u || '';
}

// ── Clock ────────────────────────────────────────────────────────────────
setInterval(() => {
    document.getElementById('clock').textContent =
        new Date().toLocaleTimeString('en-GB', { hour12: false });
}, 1000);
document.getElementById('clock').textContent =
    new Date().toLocaleTimeString('en-GB', { hour12: false });

// ── Navigation ───────────────────────────────────────────────────────────
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('page-' + btn.dataset.page).classList.add('active');
        if (btn.dataset.page === 'dashboard') loadDashboard();
        if (btn.dataset.page === 'requests')  loadAllocations();
    });
});

// ── Period window ─────────────────────────────────────────────────────────
function getPeriodWindow() {
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    if (currentView === 'week') {
        const dow = (today.getDay() + 6) % 7; // 0=Mon
        const mon = new Date(today);
        mon.setDate(today.getDate() - dow + periodOffset * 7);
        const sun = new Date(mon);
        sun.setDate(mon.getDate() + 6);
        return { start: mon, end: sun };
    }
    if (currentView === 'month') {
        const d = new Date(today.getFullYear(), today.getMonth() + periodOffset, 1);
        const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
        return { start: d, end };
    }
    // quarter
    const q = Math.floor((today.getMonth()) / 3);
    const qStart = new Date(today.getFullYear(), q * 3 + periodOffset * 3, 1);
    const qEnd   = new Date(qStart.getFullYear(), qStart.getMonth() + 3, 0);
    return { start: qStart, end: qEnd };
}

function updatePeriodLabel() {
    const { start, end } = getPeriodWindow();
    const opts1 = { day: 'numeric', month: 'short' };
    const opts2 = { day: 'numeric', month: 'short', year: 'numeric' };
    document.getElementById('period-label').textContent =
        start.toLocaleDateString('en-GB', opts1) + ' – ' +
        end.toLocaleDateString('en-GB', opts2);
}

// ── View selector ─────────────────────────────────────────────────────────
document.getElementById('view-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.tab-btn');
    if (!btn) return;
    document.querySelectorAll('#view-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentView   = btn.dataset.view;
    periodOffset  = 0;
    loadDashboard();
});

document.getElementById('btn-prev').addEventListener('click', () => { periodOffset--; loadDashboard(); });
document.getElementById('btn-next').addEventListener('click', () => { periodOffset++; loadDashboard(); });

// ── Dashboard ─────────────────────────────────────────────────────────────
async function loadDashboard() {
    updatePeriodLabel();
    const { start, end } = getPeriodWindow();
    const s = fmtDate(start), e2 = fmtDate(end);

    const [heatData, allocs] = await Promise.all([
        api('/api/heatmap?start=' + s + '&end=' + e2),
        api('/api/allocations'),
    ]);

    if (allocs)   renderStats(allocs, s, e2);
    if (heatData) renderHeatmap(heatData);
    if (heatData) renderSynopsis(heatData);
    if (allocs)   renderPeriodTable(allocs, s, e2);
    if (allocs)   renderCharts(allocs, s, e2);
}

// ── Team synopsis ─────────────────────────────────────────────────────────
function renderSynopsis(data) {
    const panel = document.getElementById('synopsis-panel');
    const body  = document.getElementById('synopsis-body');

    if (!data.resources || data.resources.length === 0) {
        panel.style.display = 'none';
        return;
    }

    // Update period label
    const { start, end } = getPeriodWindow();
    document.getElementById('synopsis-period-label').textContent =
        start.toLocaleDateString('en-GB', {day:'numeric',month:'short'}) + ' – ' +
        end.toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'});

    const weekdays = data.dates.filter(ds => { const d = new Date(ds+'T00:00:00'); return d.getDay() !== 0 && d.getDay() !== 6; });

    // ── Per-resource totals ──
    const resourceTotals = {};   // resource → total hours across period
    const resourceDays   = {};   // resource → working days with any allocation
    data.resources.forEach(r => {
        let total = 0, days = 0;
        weekdays.forEach(ds => {
            const h = (data.data[r] && data.data[r][ds]) ? data.data[r][ds].hours : 0;
            total += h;
            if (h > 0) days++;
        });
        resourceTotals[r] = total;
        resourceDays[r]   = days;
    });

    // ── Per-day totals (team combined) ──
    const dayTotals = {};
    weekdays.forEach(ds => {
        let t = 0;
        data.resources.forEach(r => { t += (data.data[r] && data.data[r][ds]) ? data.data[r][ds].hours : 0; });
        dayTotals[ds] = t;
    });

    // Busiest / quietest days (exclude zero-allocation days from quietest)
    const sortedDays  = weekdays.filter(ds => dayTotals[ds] > 0).sort((a, b) => dayTotals[b] - dayTotals[a]);
    const busiestDay  = sortedDays[0];
    const quietestDay = sortedDays[sortedDays.length - 1];

    // Most / least utilised resource (by avg hours on days they have work, or total)
    const sortedRes = data.resources.slice().sort((a, b) => resourceTotals[b] - resourceTotals[a]);
    const mostUtil  = sortedRes[0];
    const leastUtil = sortedRes[sortedRes.length - 1];

    // Active resources (at least 1 allocated day)
    const activeCount = data.resources.filter(r => resourceTotals[r] > 0).length;

    // Average daily team load (weekdays only)
    const totalTeamHours = Object.values(dayTotals).reduce((s, h) => s + h, 0);
    const avgDailyLoad   = weekdays.length > 0 ? totalTeamHours / weekdays.length : 0;

    function fmtDay(ds) {
        return new Date(ds+'T00:00:00').toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short'});
    }

    function statBlock(label, value, sub, color) {
        return `<div>
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);margin-bottom:4px">${label}</div>
            <div style="font-size:15px;font-weight:700;color:${color || 'var(--text-primary)'};font-family:var(--font-mono)">${value}</div>
            ${sub ? '<div style="font-size:10px;color:var(--text-muted);margin-top:2px">'+sub+'</div>' : ''}
        </div>`;
    }

    body.innerHTML =
        statBlock('Active Resources', activeCount + ' / ' + data.resources.length, 'people with work this period', 'var(--accent)') +
        statBlock('Avg Daily Team Load', avgDailyLoad.toFixed(1) + 'h / ' + (data.resources.length * 7.4).toFixed(1) + 'h', 'allocated vs available (' + data.resources.length + ' × 7.4h)', 'var(--info)') +
        statBlock('Busiest Day', busiestDay ? fmtDay(busiestDay) : '—',
            busiestDay ? dayTotals[busiestDay].toFixed(1) + ' combined hrs' : '', 'var(--warning)') +
        statBlock('Quietest Day', quietestDay ? fmtDay(quietestDay) : '—',
            quietestDay ? dayTotals[quietestDay].toFixed(1) + ' combined hrs' : 'no allocations', 'var(--success)') +
        statBlock('Most Utilised', resourceTotals[mostUtil] > 0 ? mostUtil : '—',
            resourceTotals[mostUtil] > 0 ? resourceTotals[mostUtil].toFixed(1) + ' hrs total' : '', 'var(--accent)') +
        statBlock('Least Utilised', resourceTotals[leastUtil] > 0 ? leastUtil : '—',
            resourceTotals[leastUtil] > 0 ? resourceTotals[leastUtil].toFixed(1) + ' hrs total' : 'no allocations', 'var(--text-secondary)');

    panel.style.display = 'block';
}

// ── Period allocations table ──────────────────────────────────────────────
function renderPeriodTable(allocs, startStr, endStr) {
    const inPeriod = allocs.filter(a => a.start_date <= endStr && a.end_date >= startStr);
    inPeriod.sort((a, b) => a.start_date.localeCompare(b.start_date) || a.resource.localeCompare(b.resource));

    document.getElementById('period-alloc-count').textContent = inPeriod.length;
    const tbody = document.getElementById('period-alloc-body');

    if (inPeriod.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px">No allocations in this period.</td></tr>';
        return;
    }

    tbody.innerHTML = inPeriod.map(a => {
        const typePill = a.type === 'Project'
            ? '<span class="pill" style="background:rgba(56,189,248,0.1);color:var(--accent)">Project</span>'
            : '<span class="pill" style="background:rgba(245,158,11,0.1);color:var(--warning)">BAU</span>';
        return '<tr>' +
            '<td class="fname">' + escHtml(a.resource) + '</td>' +
            '<td>' + typePill + '</td>' +
            '<td>' + escHtml(a.name) + '</td>' +
            '<td>' + a.start_date + '</td>' +
            '<td>' + a.end_date + '</td>' +
            '<td style="color:var(--accent)">' + a.hours_per_day + '</td>' +
            '</tr>';
    }).join('');
}

// ── Stat cards ────────────────────────────────────────────────────────────
function renderStats(allocs, ps, pe) {
    const resources  = new Set(allocs.map(a => a.resource)).size;
    const today      = TODAY_STR;
    const periodAllocs = allocs.filter(a => a.start_date <= pe && a.end_date >= ps);

    // Active: resources with at least one allocation in period
    const activePpl = new Set(periodAllocs.map(a => a.resource)).size;

    // Overloaded: resources with any day >7.4h total in period
    const dailyTotals = {};
    periodAllocs.forEach(a => {
        const s0 = a.start_date > ps ? a.start_date : ps;
        const e0 = a.end_date   < pe ? a.end_date   : pe;
        const d  = new Date(s0 + 'T00:00:00'), dEnd = new Date(e0 + 'T00:00:00');
        while (d <= dEnd) {
            if (d.getDay() !== 0 && d.getDay() !== 6) {
                const ds = fmtDate(d);
                if (!dailyTotals[a.resource]) dailyTotals[a.resource] = {};
                dailyTotals[a.resource][ds] = (dailyTotals[a.resource][ds] || 0) + a.hours_per_day;
            }
            d.setDate(d.getDate() + 1);
        }
    });
    const overloaded = Object.values(dailyTotals).reduce((sum, days) => sum + Object.values(days).filter(h => h > 7.4).length, 0);

    // Build highlight cell sets for heatmap filter
    _overloadedCells = new Set();
    Object.entries(dailyTotals).forEach(([res, days]) => {
        Object.entries(days).forEach(([date, h]) => { if (h > 7.4) _overloadedCells.add(res + '|' + date); });
    });

    _projectCells = new Set();
    periodAllocs.filter(a => a.type === 'Project').forEach(a => {
        const s0 = a.start_date > ps ? a.start_date : ps;
        const e0 = a.end_date   < pe ? a.end_date   : pe;
        const d  = new Date(s0 + 'T00:00:00'), dEnd = new Date(e0 + 'T00:00:00');
        while (d <= dEnd) {
            if (d.getDay() !== 0 && d.getDay() !== 6) _projectCells.add(a.resource + '|' + fmtDate(d));
            d.setDate(d.getDate() + 1);
        }
    });

    const projectCount = new Set(periodAllocs.filter(a => a.type === 'Project').map(a => a.name)).size;

    const cards = [
        { l: 'Resources',           v: resources,  c: 'blue',  a: 'a-blue',  sub: 'unique resources',        f: null           },
        { l: 'Allocations',         v: allocs.length, c: 'blue', a: 'a-blue', sub: 'total entries',          f: null           },
        { l: 'Active Today',        v: activePpl,  c: 'purple',a: 'a-purple',sub: 'resources with work',     f: null           },
        { l: 'Overloaded in Period',v: overloaded, c: overloaded > 0 ? 'red' : 'green',
          a: overloaded > 0 ? 'a-red' : 'a-green', sub: '&gt;7.4 hrs on any day',                            f: 'overloaded'   },
        { l: 'Projects in Period',   v: projectCount,c: 'purple',a: 'a-purple',sub: 'distinct projects',        f: 'project'      },
    ];

    document.getElementById('stats-row').innerHTML = cards.map((c, i) => {
        const isActive  = activeHeatmapFilter === c.f && c.f !== null;
        const clickable = c.f ? 'clickable-filter' : '';
        const active    = isActive ? 'filter-active' : '';
        const onclick   = c.f ? `onclick="setHeatmapFilter('${c.f}')"` : '';
        return `<div class="stat-card ${c.a} ${clickable} ${active} anim d${i+1}" ${onclick}>
            <div class="stat-label">${c.l}</div>
            <div class="stat-value ${c.c}">${c.v}</div>
            <div class="stat-sub">${c.sub}</div>
        </div>`;
    }).join('');
}

// ── Workload charts ───────────────────────────────────────────────────────
function renderCharts(allocs, ps, pe) {
    const panel = document.getElementById('charts-panel');
    const periodAllocs = allocs.filter(a => a.start_date <= pe && a.end_date >= ps);

    if (periodAllocs.length === 0) { panel.style.display = 'none'; return; }
    panel.style.display = 'block';

    const { start, end } = getPeriodWindow();
    document.getElementById('charts-period-label').textContent =
        start.toLocaleDateString('en-GB', {day:'numeric',month:'short'}) + ' – ' +
        end.toLocaleDateString('en-GB',   {day:'numeric',month:'short',year:'numeric'});

    // ── Donut: allocation count by type ──────────────────────────────────
    const projCount = periodAllocs.filter(a => a.type === 'Project').length;
    const bauCount  = periodAllocs.filter(a => a.type === 'BAU').length;
    const total     = projCount + bauCount;

    function polarXY(cx, cy, r, angle) {
        return [cx + r * Math.sin(angle), cy - r * Math.cos(angle)];
    }
    function donutArc(cx, cy, r, ir, a0, a1, fill) {
        const [x1,y1] = polarXY(cx,cy,r,a0), [x2,y2] = polarXY(cx,cy,r,a1);
        const [x3,y3] = polarXY(cx,cy,ir,a1),[x4,y4] = polarXY(cx,cy,ir,a0);
        const lg = (a1 - a0) > Math.PI ? 1 : 0;
        return `<path d="M${x1},${y1} A${r},${r} 0 ${lg},1 ${x2},${y2} L${x3},${y3} A${ir},${ir} 0 ${lg},0 ${x4},${y4} Z" fill="${fill}"/>`;
    }

    const projAngle = total > 0 ? (projCount / total) * 2 * Math.PI : 0;
    const projPct   = total > 0 ? Math.round(projCount / total * 100) : 0;
    const cx = 100, cy = 100, r = 76, ir = 46;
    let donutSvg = `<svg viewBox="0 0 200 200" width="200" height="200">`;
    if (projCount > 0 && bauCount > 0) {
        donutSvg += donutArc(cx,cy,r,ir, 0, projAngle, '#38bdf8');
        donutSvg += donutArc(cx,cy,r,ir, projAngle, 2*Math.PI, '#f59e0b');
    } else {
        donutSvg += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${projCount > 0 ? '#38bdf8' : '#f59e0b'}"/>`;
        donutSvg += `<circle cx="${cx}" cy="${cy}" r="${ir}" fill="#10151e"/>`;
    }
    donutSvg += `<text x="${cx}" y="${cy-7}" text-anchor="middle" fill="#e2e8f0" font-size="24" font-weight="700" font-family="JetBrains Mono,monospace">${total}</text>`;
    donutSvg += `<text x="${cx}" y="${cy+13}" text-anchor="middle" fill="#8b99ad" font-size="10" font-family="Outfit,sans-serif">allocations</text>`;
    donutSvg += `</svg>`;

    const legend = `<div style="display:flex;flex-direction:column;gap:10px;justify-content:center">
        <div style="display:flex;align-items:center;gap:8px;white-space:nowrap">
            <span style="width:10px;height:10px;border-radius:2px;background:#38bdf8;flex-shrink:0"></span>
            <span style="font-size:12px;color:var(--text-secondary)">Project</span>
            <span style="font-size:12px;font-weight:600;font-family:var(--font-mono);color:#38bdf8">${projCount} (${projPct}%)</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;white-space:nowrap">
            <span style="width:10px;height:10px;border-radius:2px;background:#f59e0b;flex-shrink:0"></span>
            <span style="font-size:12px;color:var(--text-secondary)">BAU</span>
            <span style="font-size:12px;font-weight:600;font-family:var(--font-mono);color:#f59e0b">${bauCount} (${100-projPct}%)</span>
        </div>
    </div>`;
    document.getElementById('chart-donut').innerHTML = donutSvg + legend;

    // ── Stacked bars: hours per resource ─────────────────────────────────
    const resources = [...new Set(periodAllocs.map(a => a.resource))].sort();
    const resHours  = {};
    resources.forEach(r => { resHours[r] = { Project: 0, BAU: 0 }; });

    periodAllocs.forEach(a => {
        const overlapStart = a.start_date > ps ? a.start_date : ps;
        const overlapEnd   = a.end_date   < pe ? a.end_date   : pe;
        let days = 0;
        const d = new Date(overlapStart + 'T00:00:00');
        const dEnd = new Date(overlapEnd + 'T00:00:00');
        while (d <= dEnd) { if (d.getDay() !== 0 && d.getDay() !== 6) days++; d.setDate(d.getDate()+1); }
        resHours[a.resource][a.type] += a.hours_per_day * days;
    });

    const maxH   = Math.max(...resources.map(r => resHours[r].Project + resHours[r].BAU), 1);
    const barH   = 24, gap = 8, labelW = 120, barMaxW = 300;
    const svgH   = resources.length * (barH + gap) + 10;
    const svgW   = labelW + barMaxW + 52;

    let barsSvg = `<svg viewBox="0 0 ${svgW} ${svgH}" width="${svgW}" height="${svgH}">`;
    resources.forEach((res, i) => {
        const y   = i * (barH + gap) + 4;
        const ph  = resHours[res].Project, bh = resHours[res].BAU;
        const tot = ph + bh;
        const pw  = (ph / maxH) * barMaxW, bw = (bh / maxH) * barMaxW;
        const short = res.length > 15 ? res.slice(0,14)+'…' : res;
        barsSvg += `<text x="${labelW-6}" y="${y+barH/2+4}" text-anchor="end" fill="#8b99ad" font-size="10" font-family="Outfit,sans-serif">${short}</text>`;
        barsSvg += `<rect x="${labelW}" y="${y}" width="${barMaxW}" height="${barH}" rx="3" fill="rgba(255,255,255,0.04)"/>`;
        if (pw > 0) barsSvg += `<rect x="${labelW}" y="${y}" width="${pw}" height="${barH}" rx="3" fill="#38bdf8"/>`;
        if (bw > 0) barsSvg += `<rect x="${labelW+pw}" y="${y}" width="${bw}" height="${barH}" rx="${pw>0?'0 3 3 0':'3'}" fill="#f59e0b"/>`;
        if (tot > 0) barsSvg += `<text x="${labelW+pw+bw+5}" y="${y+barH/2+4}" fill="#e2e8f0" font-size="9" font-family="JetBrains Mono,monospace">${tot.toFixed(0)}h</text>`;
    });
    barsSvg += `</svg>`;
    document.getElementById('chart-bars').innerHTML = barsSvg;
}

// ── Heatmap rendering ─────────────────────────────────────────────────────
function getHeatClass(hours) {
    if (hours <= 0)   return 'hm-empty';
    if (hours <= 4)   return 'hm-low';
    if (hours <= 6)   return 'hm-green';
    if (hours <= 7.4) return 'hm-amber';
    return 'hm-over';
}

function renderHeatmap(data) {
    const container = document.getElementById('heatmap-container');

    if (!data.resources || data.resources.length === 0) {
        container.style.cssText = 'min-height:80px;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:12px;font-family:var(--font-mono)';
        container.innerHTML = '<div style="padding:32px;text-align:center">No allocations in this period — add some via Resource Requests.</div>';
        return;
    }

    // Reset loading styles so position:sticky works correctly inside the table
    container.style.cssText = '';

    const isQuarter  = currentView === 'quarter';
    const spacingPx  = isQuarter ? 1 : 2;
    const weekendPx  = isQuarter ? 3 : 5;
    const labelW     = 120;
    const available  = (container.closest('.heatmap-wrap') || container).clientWidth - labelW - 24;
    const weekendCount  = data.dates.filter(ds => { const d = new Date(ds+'T00:00:00'); return d.getDay()===0||d.getDay()===6; }).length;
    const weekdayCount  = data.dates.length - weekendCount;
    const cellPx     = Math.min(28, Math.max(10, Math.floor((available - weekendPx * weekendCount - spacingPx * data.dates.length) / weekdayCount)));

    const table = document.createElement('table');
    table.className = 'heatmap-table';
    if (isQuarter) table.style.borderSpacing = spacingPx + 'px';

    // Header row
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    const corner = document.createElement('th');
    corner.style.minWidth = '120px';
    corner.style.width = '120px';
    corner.style.position = 'sticky';
    corner.style.left = '0';
    corner.style.background = 'var(--bg-card)';
    corner.style.zIndex = '3';
    corner.style.borderRight = '1px solid var(--border-subtle)';
    headerRow.appendChild(corner);

    data.dates.forEach(dateStr => {
        const th = document.createElement('th');
        th.style.padding = '0';
        const d = new Date(dateStr + 'T00:00:00');
        const dow = d.getDay();
        const isWeekend = dow === 0 || dow === 6;
        const isToday   = dateStr === TODAY_STR;
        th.style.textAlign = 'center';
        if (isWeekend) { th.style.opacity = '0.35'; th.style.width = weekendPx + 'px'; th.style.maxWidth = weekendPx + 'px'; }
        // No label on weekends; quarter view only labels Mondays
        if (!isWeekend && (!isQuarter || dow === 1)) {
            const label = document.createElement('div');
            label.className = 'hm-date-header';
            if (isToday) label.style.color = 'var(--accent)';
            label.textContent = isQuarter
                ? d.getDate() + '/' + (d.getMonth()+1)
                : d.getDate() + ' ' + d.toLocaleDateString('en-GB', { weekday: 'short' });
            th.appendChild(label);
        }
        if (isToday) th.classList.add('hm-today-col');
        headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Body rows
    const tbody = document.createElement('tbody');

    data.resources.forEach(resource => {
        const tr = document.createElement('tr');

        const nameTd = document.createElement('td');
        nameTd.className = 'heatmap-label';
        nameTd.textContent = resource;
        tr.appendChild(nameTd);

        data.dates.forEach(dateStr => {
            const td = document.createElement('td');
            td.style.padding = '1px';

            const d = new Date(dateStr + 'T00:00:00');
            const dow = d.getDay();
            const isWeekend = dow === 0 || dow === 6;
            const isToday   = dateStr === TODAY_STR;

            const cellData = (data.data[resource] || {})[dateStr];
            const hours    = cellData ? cellData.hours : 0;
            const names    = cellData ? cellData.names : [];

            const cell = document.createElement('div');
            cell.className = 'heatmap-cell ' + (isWeekend ? 'hm-empty' : getHeatClass(hours));
            const thisCellPx = isWeekend ? weekendPx : cellPx;
            cell.style.width = thisCellPx + 'px';
            cell.style.height = (isQuarter ? cellPx : 28) + 'px';
            cell.style.borderRadius = isQuarter ? '2px' : '3px';
            if (isWeekend) cell.style.opacity = '0.25';
            if (isToday) cell.style.outline = '1px solid var(--accent-dim)';

            cell.dataset.hmKey = resource + '|' + dateStr;
            cell.addEventListener('mouseenter', ev => showTooltip(ev, resource, dateStr, hours, names));
            cell.addEventListener('mouseleave', hideTooltip);
            cell.addEventListener('mousemove',  moveTooltip);

            td.appendChild(cell);
            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    container.innerHTML = '';
    container.appendChild(table);
    applyHeatmapFilter();
}

// ── Tooltip ───────────────────────────────────────────────────────────────
function showTooltip(e, resource, dateStr, hours, names) {
    const tip = document.getElementById('hm-tooltip');
    const d = new Date(dateStr + 'T00:00:00');
    const label = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    const overWarning = hours > 7.4
        ? '<span style="color:var(--danger)"> ⚠ OVERLOADED</span>'
        : '';
    const nameList = names.length > 0
        ? names.map(n => '<div style="color:var(--text-secondary)">&middot; ' + escHtml(n) + '</div>').join('')
        : '<div style="color:var(--text-muted)">No allocations</div>';

    tip.innerHTML =
        '<div style="font-weight:600;color:var(--accent);margin-bottom:4px">' + escHtml(resource) + '</div>' +
        '<div style="color:var(--text-muted);font-size:10px;margin-bottom:6px">' + label + '</div>' +
        '<div style="margin-bottom:6px">' +
        (hours > 0 ? hours.toFixed(1) + ' hrs total' + overWarning : '<span style="color:var(--text-muted)">Free</span>') +
        '</div>' +
        '<div style="line-height:1.8;font-size:10px">' + nameList + '</div>';

    tip.style.display = 'block';
    moveTooltip(e);
}

function moveTooltip(e) {
    const tip = document.getElementById('hm-tooltip');
    const offset = 16;
    let x = e.clientX + offset;
    let y = e.clientY + offset;
    if (x + 250 > window.innerWidth)  x = e.clientX - 250 - offset;
    if (y + 200 > window.innerHeight) y = e.clientY - 200 - offset;
    tip.style.left = x + 'px';
    tip.style.top  = y + 'px';
}

function hideTooltip() {
    document.getElementById('hm-tooltip').style.display = 'none';
}

// ── Allocations table ─────────────────────────────────────────────────────
async function loadAllocations() {
    const data = await api('/api/allocations');
    if (!data) return;

    document.getElementById('alloc-count').textContent = data.length;
    const tbody = document.getElementById('alloc-body');

    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:32px">No allocations yet.</td></tr>';
        return;
    }

    // Store alloc data for edit modal access
    window._allocData = {};
    data.forEach(a => { window._allocData[a.id] = a; });

    tbody.innerHTML = data.map(a => {
        const typePill = a.type === 'Project'
            ? '<span class="pill" style="background:rgba(56,189,248,0.1);color:var(--accent)">Project</span>'
            : '<span class="pill" style="background:rgba(245,158,11,0.1);color:var(--warning)">BAU</span>';
        return '<tr>' +
            '<td class="fname">' + escHtml(a.resource) + '</td>' +
            '<td>' + typePill + '</td>' +
            '<td>' + escHtml(a.name) + '</td>' +
            '<td>' + escHtml(a.crq_number || '') + '</td>' +
            '<td>' + escHtml(a.requestor || '') + '</td>' +
            '<td>' + a.start_date + '</td>' +
            '<td>' + a.end_date + '</td>' +
            '<td style="color:var(--accent)">' + a.hours_per_day + '</td>' +
            '<td>' + (a.created_at || '').slice(0, 10) + '</td>' +
            '<td style="display:flex;gap:6px">' +
            '<button class="btn btn-sm" onclick="openEditModal(window._allocData[\'' + a.id + '\'])">Edit</button>' +
            '<button class="btn btn-sm btn-danger" onclick="deleteAlloc(\'' + a.id + '\')">Delete</button>' +
            '</td>' +
            '</tr>';
    }).join('');
}

// ── Heatmap filter ────────────────────────────────────────────────────────
function setHeatmapFilter(filter) {
    activeHeatmapFilter = activeHeatmapFilter === filter ? null : filter;
    applyHeatmapFilter();
    // Refresh stat cards to update active state without full reload
    document.querySelectorAll('.stat-card.clickable-filter').forEach(card => {
        const f = card.getAttribute('onclick').match(/'(\w+)'/)?.[1];
        card.classList.toggle('filter-active', f === activeHeatmapFilter);
    });
}

function applyHeatmapFilter() {
    const cells = document.querySelectorAll('[data-hm-key]');
    if (!activeHeatmapFilter) {
        cells.forEach(c => { c.classList.remove('hm-highlight', 'hm-dimmed'); });
        return;
    }
    const activeSet = activeHeatmapFilter === 'project' ? _projectCells : _overloadedCells;
    cells.forEach(c => {
        const match = activeSet.has(c.dataset.hmKey);
        c.classList.toggle('hm-highlight', match);
        c.classList.toggle('hm-dimmed',    !match);
    });
}

// ── Panel collapse ────────────────────────────────────────────────────────
function togglePanel(panel) {
    const collapsed = panel.classList.toggle('collapsed');
    if (panel.id) localStorage.setItem('pc-' + panel.id, collapsed ? '1' : '');
}

function restorePanelStates() {
    document.querySelectorAll('.panel[id]').forEach(panel => {
        if (localStorage.getItem('pc-' + panel.id) === '1') togglePanel(panel);
    });
}

// ── CRQ show/hide ─────────────────────────────────────────────────────────
function toggleCrqField(groupId, typeVal) {
    document.getElementById(groupId).style.display = typeVal === 'Project' ? '' : 'none';
}

// ── Form submit ───────────────────────────────────────────────────────────
async function submitAlloc(e) {
    e.preventDefault();
    const body = {
        resource:      document.getElementById('f-resource').value.trim(),
        type:          document.getElementById('f-type').value,
        name:          document.getElementById('f-name').value.trim(),
        crq_number:    document.getElementById('f-crq').value.trim(),
        requestor:     document.getElementById('f-requestor').value.trim(),
        start_date:    document.getElementById('f-start').value,
        end_date:      document.getElementById('f-end').value,
        hours_per_day: parseFloat(document.getElementById('f-hours').value),
    };
    if (!body.resource)   { toast('Resource name is required', 'error'); return; }
    if (!body.type)       { toast('Please select a type', 'error'); return; }
    if (!body.name)       { toast('Name is required', 'error'); return; }
    if (body.start_date > body.end_date) { toast('End date must be on or after start date', 'error'); return; }
    if (isNaN(body.hours_per_day) || body.hours_per_day <= 0) { toast('Enter a valid hours/day value', 'error'); return; }

    const r = await api('/api/allocations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });

    if (r && r.id) {
        toast('Allocation created', 'success');
        document.getElementById('alloc-form').reset();
        document.getElementById('f-resource').value = getUsername();
        const today = fmtDate(new Date());
        document.getElementById('f-start').value = today;
        document.getElementById('f-end').value   = today;
        document.getElementById('f-hours').value  = '7.4';
        loadAllocations();
    } else {
        toast('Error: ' + (r && r.error ? r.error : 'unknown'), 'error');
    }
}

// ── Edit modal ────────────────────────────────────────────────────────────
function openEditModal(a) {
    document.getElementById('e-id').value        = a.id;
    document.getElementById('e-resource').value  = a.resource;
    document.getElementById('e-type').value      = a.type;
    document.getElementById('e-name').value      = a.name;
    document.getElementById('e-crq').value       = a.crq_number || '';
    document.getElementById('e-requestor').value = a.requestor || '';
    document.getElementById('e-start').value     = a.start_date;
    document.getElementById('e-end').value       = a.end_date;
    document.getElementById('e-hours').value     = a.hours_per_day;
    toggleCrqField('e-crq-group', a.type);
    document.getElementById('edit-modal').classList.add('open');
}

function closeEditModal() {
    document.getElementById('edit-modal').classList.remove('open');
}

// Close on backdrop click
document.getElementById('edit-modal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeEditModal();
});

async function submitEdit(e) {
    e.preventDefault();
    const id = document.getElementById('e-id').value;
    const body = {
        resource:      document.getElementById('e-resource').value.trim(),
        type:          document.getElementById('e-type').value,
        name:          document.getElementById('e-name').value.trim(),
        crq_number:    document.getElementById('e-crq').value.trim(),
        requestor:     document.getElementById('e-requestor').value.trim(),
        start_date:    document.getElementById('e-start').value,
        end_date:      document.getElementById('e-end').value,
        hours_per_day: parseFloat(document.getElementById('e-hours').value),
    };
    if (body.start_date > body.end_date) { toast('End date must be on or after start date', 'error'); return; }

    const r = await api('/api/allocations/' + id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });

    if (r && r.status === 'updated') {
        toast('Allocation updated', 'success');
        closeEditModal();
        loadAllocations();
    } else {
        toast('Error: ' + (r && r.error ? r.error : 'unknown'), 'error');
    }
}

// ── Delete ────────────────────────────────────────────────────────────────
async function deleteAlloc(id) {
    if (!confirm('Delete this allocation?')) return;
    const r = await api('/api/allocations/' + id, { method: 'DELETE' });
    if (r && r.status === 'deleted') {
        toast('Allocation deleted', 'info');
        loadAllocations();
    } else {
        toast('Delete failed', 'error');
    }
}

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const username = getUsername();
    document.getElementById('f-resource').value = username;

    const today = fmtDate(new Date());
    document.getElementById('f-start').value = today;
    document.getElementById('f-end').value   = today;

    restorePanelStates();
    loadDashboard();
    setInterval(loadDashboard, 60000);
});
</script>
</body>
</html>'''


# ======================================================================
# HTTP API Handler
# ======================================================================

class APIHandler(BaseHTTPRequestHandler):
    db: Database = None

    def log_message(self, format, *args):
        pass  # suppress request noise

    def _json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path   = parsed.path.rstrip("/") or "/"
            params = parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self._html(build_app_html())

            elif path == "/api/allocations":
                resource = params.get("resource", [None])[0]
                start    = params.get("start",    [None])[0]
                end      = params.get("end",      [None])[0]

                sql  = "SELECT * FROM allocations WHERE 1=1"
                args = []
                if resource:
                    sql += " AND resource=?"; args.append(resource)
                if start:
                    sql += " AND end_date>=?"; args.append(start)
                if end:
                    sql += " AND start_date<=?"; args.append(end)
                sql += " ORDER BY start_date, resource"

                rows = self.db.fetchall(sql, args)
                self._json([dict(r) for r in rows])

            elif path == "/api/resources":
                rows = self.db.fetchall(
                    "SELECT DISTINCT resource FROM allocations ORDER BY resource"
                )
                self._json({"resources": [r["resource"] for r in rows]})

            elif path == "/api/heatmap":
                self._json(self._get_heatmap(params))

            else:
                self._json({"error": "Not found"}, 404)

        except Exception as exc:
            log.exception("GET error")
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path   = parsed.path.rstrip("/")

            if path == "/api/allocations":
                body = self._read_body()
                resource      = (body.get("resource") or "").strip()
                atype         = (body.get("type") or "").strip()
                name          = (body.get("name") or "").strip()
                crq_number    = (body.get("crq_number") or "").strip()
                requestor     = (body.get("requestor") or "").strip()
                start_date    = (body.get("start_date") or "").strip()
                end_date      = (body.get("end_date") or "").strip()
                hours_per_day = body.get("hours_per_day")

                if not all([resource, atype, name, start_date, end_date]):
                    return self._json({"error": "All fields are required"}, 400)
                if atype not in ("Project", "BAU"):
                    return self._json({"error": "type must be Project or BAU"}, 400)
                if start_date > end_date:
                    return self._json({"error": "start_date must be <= end_date"}, 400)
                try:
                    hours_per_day = float(hours_per_day)
                    if hours_per_day <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return self._json({"error": "hours_per_day must be a positive number"}, 400)

                aid = self.db.new_id("alloc-")
                self.db.execute(
                    "INSERT INTO allocations "
                    "(id, resource, type, name, crq_number, requestor, start_date, end_date, hours_per_day, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (aid, resource, atype, name, crq_number, requestor, start_date, end_date, hours_per_day,
                     datetime.now().isoformat()),
                )
                self._json({"id": aid, "status": "created"}, 201)
            else:
                self._json({"error": "Not found"}, 404)

        except Exception as exc:
            log.exception("POST error")
            self._json({"error": str(exc)}, 500)

    def do_PUT(self):
        try:
            path  = urlparse(self.path).path.rstrip("/")
            parts = path.split("/")

            if len(parts) == 4 and parts[1] == "api" and parts[2] == "allocations":
                aid  = parts[3]
                body = self._read_body()
                resource      = (body.get("resource") or "").strip()
                atype         = (body.get("type") or "").strip()
                name          = (body.get("name") or "").strip()
                crq_number    = (body.get("crq_number") or "").strip()
                requestor     = (body.get("requestor") or "").strip()
                start_date    = (body.get("start_date") or "").strip()
                end_date      = (body.get("end_date") or "").strip()
                hours_per_day = body.get("hours_per_day")

                if not all([resource, atype, name, start_date, end_date]):
                    return self._json({"error": "All fields are required"}, 400)
                if atype not in ("Project", "BAU"):
                    return self._json({"error": "type must be Project or BAU"}, 400)
                if start_date > end_date:
                    return self._json({"error": "start_date must be <= end_date"}, 400)
                try:
                    hours_per_day = float(hours_per_day)
                    if hours_per_day <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return self._json({"error": "hours_per_day must be a positive number"}, 400)

                self.db.execute(
                    "UPDATE allocations SET resource=?, type=?, name=?, crq_number=?, requestor=?, start_date=?, end_date=?, hours_per_day=? WHERE id=?",
                    (resource, atype, name, crq_number, requestor, start_date, end_date, hours_per_day, aid),
                )
                self._json({"status": "updated"})
            else:
                self._json({"error": "Not found"}, 404)

        except Exception as exc:
            log.exception("PUT error")
            self._json({"error": str(exc)}, 500)

    def do_DELETE(self):
        try:
            path = urlparse(self.path).path.rstrip("/")
            parts = path.split("/")

            if len(parts) == 4 and parts[1] == "api" and parts[2] == "allocations":
                aid = parts[3]
                self.db.execute("DELETE FROM allocations WHERE id=?", (aid,))
                self._json({"status": "deleted"})
            else:
                self._json({"error": "Not found"}, 404)

        except Exception as exc:
            log.exception("DELETE error")
            self._json({"error": str(exc)}, 500)

    # ── Heatmap aggregation ───────────────────────────────────────────────
    def _get_heatmap(self, params):
        start_str = params.get("start", [None])[0]
        end_str   = params.get("end",   [None])[0]

        today = date.today()
        if not start_str or not end_str:
            dow   = today.weekday()
            start = today - timedelta(days=dow)
            end   = start + timedelta(days=27)
        else:
            try:
                start = date.fromisoformat(start_str)
                end   = date.fromisoformat(end_str)
            except ValueError:
                start = today
                end   = today + timedelta(days=6)

        # Cap at 92 days (quarter)
        if (end - start).days > 92:
            end = start + timedelta(days=92)

        n_days    = (end - start).days + 1
        all_dates = [(start + timedelta(days=i)).isoformat() for i in range(n_days)]

        rows = self.db.fetchall(
            "SELECT resource, start_date, end_date, hours_per_day, name "
            "FROM allocations WHERE end_date >= ? AND start_date <= ? "
            "ORDER BY resource, start_date",
            (start.isoformat(), end.isoformat()),
        )

        result   = {}
        res_seen = []

        for row in rows:
            r = row["resource"]
            if r not in result:
                result[r] = {}
                res_seen.append(r)

            a_start = date.fromisoformat(row["start_date"])
            a_end   = date.fromisoformat(row["end_date"])
            h       = row["hours_per_day"]
            name    = row["name"]

            eff_start = max(a_start, start)
            eff_end   = min(a_end,   end)

            cur = eff_start
            while cur <= eff_end:
                ds = cur.isoformat()
                if ds not in result[r]:
                    result[r][ds] = {"hours": 0.0, "names": []}
                result[r][ds]["hours"] += h
                if name not in result[r][ds]["names"]:
                    result[r][ds]["names"].append(name)
                cur += timedelta(days=1)

        res_seen.sort()

        return {
            "resources": res_seen,
            "dates":     all_dates,
            "data":      result,
        }


# ======================================================================
# Entry Point
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Py Resourcing — Team Resource Manager")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port (default 8460)")
    parser.add_argument("--db",   type=str, default=str(DB_FILE),  help="SQLite database path")
    args = parser.parse_args()

    db_path = Path(args.db)
    db = Database(db_path)
    log.info("Database: %s", db_path.resolve())

    APIHandler.db = db

    server = HTTPServer(("0.0.0.0", args.port), APIHandler)

    print(
        "\033[36m"
        "╔══════════════════════════════════════════╗\n"
        "║         Py Resourcing  v1.0              ║\n"
        "║──────────────────────────────────────────║\n"
        f"║  Dashboard : http://localhost:{args.port}      ║\n"
        f"║  Database  : {str(db_path.name):<28} ║\n"
        "╚══════════════════════════════════════════╝"
        "\033[0m"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
