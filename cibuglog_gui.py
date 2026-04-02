#!/usr/bin/env python3
"""
CIBugLog Query Tool
-------------------
GUI application for querying and analyzing CI test results from CIBugLog.

Requirements:
    pip install requests beautifulsoup4
"""

import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import threading
import urllib.parse
import re
import webbrowser
import csv
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from requests_negotiate_sspi import HttpNegotiateAuth
    HAS_SSPI = True
except ImportError:
    HAS_SSPI = False

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

CIBUGLOG_ROOT_OPTIONS = [
    "https://gfx-ci.igk.intel.com/cibuglog-ng/",
    "https://gfx-ci-internal.igk.intel.com/cibuglog",
]
PAGE_SIZE = 100
PROXIES = {
    "http":  "http://proxy-dmz.intel.com:912",
    "https": "http://proxy-dmz.intel.com:912",
}
HISTORY_FILE = Path(__file__).with_name("cibuglog_history.json")

STATUS_COLORS = {
    "pass":       ("#d4edda", "#155724"),
    "fail":       ("#f8d7da", "#721c24"),
    "dmesg":      ("#fce4e4", "#721c24"),
    "skip":       ("#fff3cd", "#856404"),
    "incomplete": ("#e2e3e5", "#383d41"),
    "notrun":     ("#e2e3e5", "#383d41"),
}


def classify_status(status_text: str) -> str:
    sl = status_text.lower()
    if "dmesg-fail" in sl or ("dmesg" in sl and "fail" in sl) or "abort" in sl:
        return "dmesg"
    if "fail" in sl:
        return "fail"
    if "pass" in sl:
        return "pass"
    if "skip" in sl:
        return "skip"
    if "incomplete" in sl or "notrun" in sl:
        return "incomplete"
    return ""


def clean_cell(text: str) -> str:
    text = re.sub(r"\(external\s*URL\)", "", text)
    text = re.sub(r"^IGT:\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_external_link_marker(text: str) -> bool:
    return bool(re.search(r"external\s*url", text or "", re.I))


def _normalize_result_url(url: str, jira_base: str, cibuglog_base: str) -> str:
    u = (url or "").strip()
    if not u or u.startswith("#"):
        return ""
    if u.startswith("http"):
        return u
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/browse/"):
        return jira_base + u
    if u.startswith("/"):
        return cibuglog_base + u
    return u


def _looks_like_tree_url(url: str) -> bool:
    return bool(re.search(r"(^|/)tree(?:[/?#]|$)", url or "", re.I))


def _build_tree_url_from_row(
    test_name: str,
    machine_name: str,
    build_text: str,
    cibuglog_origin: str,
    tags_text: str = "",
) -> str:
    test = (test_name or "").strip()
    machine = (machine_name or "").strip()
    build = (build_text or "").strip()
    tags = (tags_text or "").strip()
    if not test or not machine or not build:
        return ""

    # Newer rows carry tree path as: <tags>/<runconfig>.
    # Strip UI suffixes like "(1 day old)" before URL assembly.
    build_clean = re.sub(r"\s*\([^)]*\)\s*$", "", build).strip()
    tags_clean = re.sub(r"\s*\([^)]*\)\s*$", "", tags).strip()

    # Build from tags only when tags look like a single path token.
    if (
        tags_clean
        and build_clean
        and "/" not in build_clean
        and "," not in tags_clean
        and re.fullmatch(r"[A-Za-z0-9._@+-]+", tags_clean)
    ):
        tags_part = urllib.parse.quote(tags_clean, safe="@._-+")
        build_part = urllib.parse.quote(build_clean, safe="@._-+")
        test_part = urllib.parse.quote(test, safe="@._-+")
        machine_part = urllib.parse.quote(machine, safe="@._-+")
        return (
            f"{cibuglog_origin.rstrip('/')}/tree/{tags_part}/{build_part}/"
            f"{machine_part}/{test_part}.html"
        )

    # Heuristic for RTL validation builds, e.g. xe-rtl-val-jgs-153-full.
    rtl_m = re.match(r"^(xe-rtl-val-([a-z0-9]+)-\d+)(?:-[a-z0-9]+)?$", build_clean, re.I)
    if rtl_m:
        build_part = rtl_m.group(1)
        platform = rtl_m.group(2).lower()
        tags_part = f"xe-rtl-validation-{platform}"
        test_part = urllib.parse.quote(test, safe="@._-+")
        machine_part = urllib.parse.quote(machine, safe="@._-+")
        return (
            f"{cibuglog_origin.rstrip('/')}/tree/{tags_part}/{build_part}/"
            f"{machine_part}/{test_part}.html"
        )

    m = re.search(r"\b(xe-\d+)\b", build, re.I)
    if not m:
        return ""

    build_id = m.group(1)
    test_part = urllib.parse.quote(test, safe="@._-+")
    machine_part = urllib.parse.quote(machine, safe="@._-+")
    return (
        f"{cibuglog_origin.rstrip('/')}/tree/xe/{build_id}/"
        f"{machine_part}/{test_part}.html"
    )


class CIBugLogApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CIBugLog & JIRA Query Tool")
        self.geometry("1440x900")
        self.minsize(1000, 650)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"))

        self._sort_reverse = {}
        self._query_history: list[str] = []
        self._field_history: dict[str, list[str]] = {
            "test": [], "machine": [], "runconfig": [], "date": []
        }
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        
        # JIRA Query tab (first)
        self.jira_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.jira_frame, text="JIRA Query")
        
        # CIBugLog tab (second)
        self.cibuglog_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.cibuglog_frame, text="CIBugLog")
        
        self._build_jira_ui()
        self._build_cibuglog_ui()
        self._load_history()
        self._check_deps()
        self.after(250, self._auto_fetch_jira_on_startup)

    # ------------------------------------------------------------------ UI --

    def _build_cibuglog_ui(self):
        # ---- Filter frame ----
        fframe = ttk.LabelFrame(self.cibuglog_frame, text=" Query Filters ", padding=(12, 6))
        fframe.pack(fill="x", padx=10, pady=(10, 4))
        fframe.columnconfigure(3, weight=1)

        for col, txt in enumerate(["Connector", "Field", "Match type", "Value"]):
            ttk.Label(fframe, text=txt, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=col, padx=8, pady=(2, 4), sticky="w")

        # Row 1 – test_name
        ttk.Label(fframe, text="(first)", foreground="gray").grid(
            row=1, column=0, padx=8, pady=3, sticky="w")
        ttk.Label(fframe, text="test_name").grid(
            row=1, column=1, padx=8, pady=3, sticky="w")
        self.test_match = self._combo(fframe, ["= (exact)", "~= (regex/contains)"], "= (exact)", 1, 2)
        self.test_value = ttk.Combobox(fframe, font=("Consolas", 10))
        self.test_value.grid(row=1, column=3, padx=8, pady=3, sticky="ew")
        ttk.Label(fframe, text="e.g.  igt@xe_eudebug_online@basic-breakpoint",
                  foreground="gray").grid(row=1, column=4, padx=4, sticky="w")

        # Row 2 – machine_name
        self.machine_conn = self._combo(fframe, ["AND", "AND NOT"], "AND", 2, 0)
        ttk.Label(fframe, text="machine_name").grid(
            row=2, column=1, padx=8, pady=3, sticky="w")
        self.machine_match = self._combo(fframe, ["= (exact)", "~= (regex/contains)"], "~= (regex/contains)", 2, 2)
        self.machine_value = ttk.Combobox(fframe, font=("Consolas", 10))
        self.machine_value.grid(row=2, column=3, padx=8, pady=3, sticky="ew")
        ttk.Label(fframe, text="e.g.  jgs  or  cri|jgs  or  BMG",
                  foreground="gray").grid(row=2, column=4, padx=4, sticky="w")

        # Row 3 – runconfig_name
        self.rc_conn = self._combo(fframe, ["AND", "AND NOT"], "AND NOT", 3, 0)
        ttk.Label(fframe, text="runconfig_name").grid(
            row=3, column=1, padx=8, pady=3, sticky="w")
        self.rc_match = self._combo(fframe, ["= (exact)", "~= (regex/contains)"], "~= (regex/contains)", 3, 2)
        self.rc_value = ttk.Combobox(fframe, font=("Consolas", 10))
        self.rc_value.grid(row=3, column=3, padx=8, pady=3, sticky="ew")
        ttk.Label(fframe, text="e.g.  kasan|upstream",
                  foreground="gray").grid(row=3, column=4, padx=4, sticky="w")

        # Row 4 – date filter
        ttk.Label(fframe, text="AND").grid(row=4, column=0, padx=8, sticky="w")
        ttk.Label(fframe, text="runconfig_added_on >").grid(
            row=4, column=1, padx=8, pady=3, sticky="w")
        ttk.Label(fframe, text="datetime( ... )").grid(
            row=4, column=2, padx=8, sticky="w")
        date_row = ttk.Frame(fframe)
        date_row.grid(row=4, column=3, padx=8, pady=3, sticky="w")
        self.date_value = ttk.Combobox(date_row, width=18, font=("Consolas", 10))
        self.date_value.grid(row=0, column=0)
        ttk.Label(date_row, text="  e.g. 2026-03-31   (optional)",
                  foreground="gray").grid(row=0, column=1, padx=4)

        # ---- Query preview ----
        pframe = ttk.LabelFrame(self.cibuglog_frame, text=" Query Preview ", padding=(10, 4))
        pframe.pack(fill="x", padx=10, pady=4)
        pframe.columnconfigure(0, weight=1)

        self.query_var = tk.StringVar()
        self.query_entry = ttk.Combobox(pframe, textvariable=self.query_var,
                                        font=("Consolas", 10), values=[],
                                        postcommand=self._refresh_history_dropdown)
        self.query_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.query_entry.bind("<KeyRelease>", self._on_query_edit)
        self.query_entry.bind("<<Paste>>",    self._on_query_paste)
        self.query_entry.bind("<<ComboboxSelected>>", self._on_history_select)
        ttk.Button(pframe, text="Parse ↑", width=8,
                   command=self._parse_query_to_fields).grid(row=0, column=1, padx=2)
        ttk.Button(pframe, text="Copy", width=7,
                   command=self._copy_query).grid(row=0, column=2, padx=2)
        ttk.Button(pframe, text="Browser", width=8,
                   command=self._open_browser).grid(row=0, column=3, padx=2)

        # ---- Action bar ----
        bframe = ttk.Frame(self.cibuglog_frame)
        bframe.pack(fill="x", padx=10, pady=4)

        ttk.Button(bframe, text="▶  Fetch Results", command=self._fetch_async,
                   style="Accent.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(bframe, text="Export CSV",
                   command=self._export_csv).pack(side="left", padx=4)
        ttk.Button(bframe, text="Clear All",
                   command=self._clear_all).pack(side="left", padx=4)

        ttk.Label(bframe, text="CIBugLog:").pack(side="left", padx=(16, 4))
        self.cibuglog_root_var = tk.StringVar(value=CIBUGLOG_ROOT_OPTIONS[1])
        self.cibuglog_root_cb = ttk.Combobox(
            bframe,
            textvariable=self.cibuglog_root_var,
            values=CIBUGLOG_ROOT_OPTIONS,
            state="readonly",
            width=50,
            font=("Segoe UI", 10, "bold"),
        )
        self.cibuglog_root_cb.pack(side="left", padx=(0, 8))

        self.use_proxy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bframe, text="Use proxy",
                        variable=self.use_proxy_var).pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = ttk.Label(bframe, textvariable=self.status_var, foreground="gray")
        self.status_lbl.pack(side="left", padx=16)

        self.progress = ttk.Progressbar(bframe, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=6)

        # ---- Count / pagination label ----
        self.count_var = tk.StringVar(value="")
        ttk.Label(self.cibuglog_frame, textvariable=self.count_var,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=1)

        # ---- Results table ----
        tframe = ttk.Frame(self.cibuglog_frame)
        tframe.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tframe.rowconfigure(0, weight=1)
        tframe.columnconfigure(0, weight=1)

        cols = ("test", "runconfig", "tags", "status", "build", "issue")
        self.tree = ttk.Treeview(tframe, columns=cols, show="headings", selectmode="extended")

        col_cfg = [
            ("test",      "Test Name",   340),
            ("runconfig", "Machine",     220),
            ("tags",      "Tags",        160),
            ("status",    "Status",      110),
            ("build",     "Run Config",  220),
            ("issue",     "Issue",       320),
        ]
        for cid, heading, width in col_cfg:
            self.tree.heading(cid, text=heading,
                              command=lambda c=cid: self._sort_column(c))
            self.tree.column(cid, width=width, minwidth=60, stretch=True)

        for key, (bg, fg) in STATUS_COLORS.items():
            self.tree.tag_configure(key, background=bg, foreground=fg)

        vsb = ttk.Scrollbar(tframe, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tframe, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Context menu – rebuilt dynamically on each right-click
        self._ctx = tk.Menu(self, tearoff=0)
        self.tree.bind("<ButtonRelease-3>", self._show_ctx)
        self.tree.bind("<Control-Button-1>", self._show_ctx)
        self._ctx_col = None

        # Auto-update preview
        for w in (self.test_value, self.machine_value, self.rc_value, self.date_value):
            w.bind("<KeyRelease>", lambda _: self._update_preview())
            w.bind("<<ComboboxSelected>>", lambda _: self._update_preview())
        for w in (self.test_match, self.machine_conn, self.machine_match,
                  self.rc_conn, self.rc_match):
            w.bind("<<ComboboxSelected>>", lambda _: self._update_preview())

    def _build_jira_ui(self):
        """Build JIRA Query tab with issues table."""
        # Default JIRA query
        default_jql = (
            "project = VLK AND component = XeKMD AND component = \"Kernel - core\" "
            "AND priority = Undecided AND Exposure = Unset AND status != Closed "
            "AND status != Rejected AND type = Bug"
        )
        
        # ---- Query Field ----
        qframe = ttk.LabelFrame(self.jira_frame, text=" JQL Query ", padding=(10, 4))
        qframe.pack(fill="x", padx=10, pady=(10, 4))
        qframe.columnconfigure(0, weight=1)
        
        self.jira_query_text = tk.Text(qframe, font=("Consolas", 9), height=3, width=100)
        self.jira_query_text.pack(fill="both", expand=False, padx=6, pady=4)
        self.jira_query_text.insert("1.0", default_jql)
        
        # ---- Action Buttons ----
        btn_frame = ttk.Frame(self.jira_frame)
        btn_frame.pack(fill="x", padx=10, pady=(4, 4))
        
        ttk.Button(btn_frame, text="▶  Fetch Issues", 
                   command=self._on_fetch_jira_clicked,
                   style="Accent.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btn_frame, text="Open in JIRA",
                   command=self._on_open_jira_clicked).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Copy Query",
                   command=self._on_copy_jira_clicked).pack(side="left", padx=4)
        
        self.jira_status_label = ttk.Label(btn_frame, text="Ready", foreground="gray")
        self.jira_status_label.pack(side="left", padx=16)
        
        self.jira_progress = ttk.Progressbar(btn_frame, mode="indeterminate", length=180)
        self.jira_progress.pack(side="right", padx=6)

        # ---- Inline filter (highlight matching rows) ----
        filter_frame = ttk.Frame(self.jira_frame)
        filter_frame.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(filter_frame, text="Filter:").pack(side="left")
        self.jira_filter_var = tk.StringVar(value="eudebug")
        self.jira_filter_entry = ttk.Entry(filter_frame, textvariable=self.jira_filter_var)
        self.jira_filter_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.jira_filter_entry.bind("<KeyRelease>", self._on_jira_filter_changed)
        
        # ---- Count label ----
        self.jira_count_var = tk.StringVar(value="")
        ttk.Label(self.jira_frame, textvariable=self.jira_count_var,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=1)
        
        # ---- Results table ----
        tframe = ttk.Frame(self.jira_frame)
        tframe.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tframe.rowconfigure(0, weight=1)
        tframe.columnconfigure(0, weight=1)
        
        cols = ("key", "created", "summary", "labels", "status", "assignee")
        self.jira_tree = ttk.Treeview(tframe, columns=cols, show="headings", selectmode="extended")
        
        col_cfg = [
            ("key",      "Key",       100),
            ("created",  "Created",   135),
            ("summary",  "Summary",   420),
            ("labels",   "Labels",    160),
            ("status",   "Status",    100),
            ("assignee", "Assignee",  150),
        ]
        for cid, heading, width in col_cfg:
            self.jira_tree.heading(cid, text=heading,
                                   command=lambda c=cid: self._sort_jira_column(c))
            self.jira_tree.column(
                cid,
                width=width,
                minwidth=60,
                stretch=(cid == "summary"),
            )
        
        vsb = ttk.Scrollbar(tframe, orient="vertical",   command=self.jira_tree.yview)
        hsb = ttk.Scrollbar(tframe, orient="horizontal", command=self.jira_tree.xview)
        self.jira_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.jira_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.jira_tree.tag_configure("jira_filter_match", background="#fff59d")

        # Context menu for JIRA rows
        self._jira_ctx = tk.Menu(self, tearoff=0)
        self._jira_ctx_col = None
        self.jira_tree.bind("<ButtonRelease-3>", self._show_jira_ctx)
        self.jira_tree.bind("<Control-Button-1>", self._show_jira_ctx)
        
        # Store sort state for JIRA table
        self._jira_sort_reverse = {}

    def _get_jira_query(self) -> str:
        """Get JQL query from text widget."""
        return self.jira_query_text.get("1.0", "end").strip()

    def _on_fetch_jira_clicked(self):
        """Handle Fetch Issues button click."""
        jql = self._get_jira_query()
        if not jql:
            messagebox.showwarning("Empty query", "Please enter a JQL query.")
            return
        self._fetch_jira_issues(jql)

    def _on_open_jira_clicked(self):
        """Handle Open in JIRA button click."""
        jql = self._get_jira_query()
        if not jql:
            messagebox.showwarning("Empty query", "Please enter a JQL query.")
            return
        self._open_jira_search(jql)

    def _on_copy_jira_clicked(self):
        """Handle Copy Query button click."""
        jql = self._get_jira_query()
        if not jql:
            messagebox.showwarning("Empty query", "Please enter a JQL query.")
            return
        self.clipboard_clear()
        self.clipboard_append(jql)
        self.jira_status_label.configure(text="Query copied to clipboard", foreground="gray")

    def _auto_fetch_jira_on_startup(self):
        """Fetch JIRA issues automatically once the app starts."""
        if not HAS_REQUESTS:
            return
        jql = self._get_jira_query()
        if jql:
            self._fetch_jira_issues(jql)

    def _fetch_jira_issues(self, jql: str):
        """Fetch issues from JIRA and display in table."""
        if not HAS_REQUESTS:
            messagebox.showerror("Missing dependency",
                                 "Run: pip install requests")
            return
        
        self.jira_status_label.configure(text="Fetching …", foreground="gray")
        self.jira_count_var.set("")
        self._clear_jira_table()
        self.jira_progress.start(10)
        self.jira_frame.update()
        
        def worker():
            try:
                token_file = Path(__file__).with_name("jira_token")
                try:
                    token = token_file.read_text(encoding="utf-8").strip()
                except OSError:
                    token = os.getenv("JIRA_TOKEN", "")
                
                if not token:
                    def show_error():
                        self.jira_status_label.configure(text="Error: No JIRA token found",
                                                         foreground="red")
                        self.jira_count_var.set("—")
                    self.after(0, show_error)
                    return
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                }
                
                base_url = os.getenv("JIRA_BASE_URL", "https://jira.devtools.intel.com")
                url = f"{base_url.rstrip('/')}/rest/api/2/search"
                
                # Fetch all issues that match the query
                all_issues = []
                start_at = 0
                max_results = 100
                
                while True:
                    params = {
                        "jql": jql,
                        "startAt": start_at,
                        "maxResults": max_results,
                        "fields": "key,created,summary,status,priority,assignee,labels",
                    }
                    
                    resp = requests.get(url, headers=headers, params=params,
                                       timeout=60, verify=False)
                    resp.raise_for_status()
                    
                    data = resp.json()
                    issues = data.get("issues", [])
                    all_issues.extend(issues)
                    
                    total = data.get("total", 0)
                    if start_at + max_results >= total:
                        break
                    
                    start_at += max_results
                
                def populate():
                    self.jira_progress.stop()
                    self._populate_jira_table(all_issues)
                    self.jira_count_var.set(f"Total: {len(all_issues)} issues")
                    self.jira_status_label.configure(text="Done", foreground="gray")
                
                self.after(0, populate)
                
            except requests.exceptions.ConnectionError as exc:
                def show_conn_error():
                    self.jira_progress.stop()
                    self.jira_status_label.configure(
                        text="Error: Connection failed (check VPN)", foreground="red")
                    self.jira_count_var.set("—")
                self.after(0, show_conn_error)
                
            except requests.exceptions.HTTPError as exc:
                def show_http_error():
                    self.jira_progress.stop()
                    self.jira_status_label.configure(
                        text=f"Error: HTTP {exc.response.status_code}", foreground="red")
                    self.jira_count_var.set("—")
                self.after(0, show_http_error)
                
            except Exception as exc:
                import traceback
                def show_generic_error():
                    self.jira_progress.stop()
                    self.jira_status_label.configure(
                        text=f"Error: {type(exc).__name__}: {str(exc)[:50]}", foreground="red")
                    self.jira_count_var.set("—")
                self.after(0, show_generic_error)
                print(f"JIRA fetch error: {traceback.format_exc()}", file=sys.stderr)
        
        threading.Thread(target=worker, daemon=True).start()

    def _clear_jira_table(self):
        """Clear JIRA results table."""
        for item in self.jira_tree.get_children():
            self.jira_tree.delete(item)

    def _populate_jira_table(self, issues: list):
        """Populate JIRA table with fetched issues."""
        self._clear_jira_table()
        
        for issue in issues:
            fields = issue.get("fields", {})
            key = issue.get("key", "")
            created = self._format_jira_created(fields.get("created", ""))
            summary = fields.get("summary", "")
            status = fields.get("status", {})
            status_name = status.get("name", "") if isinstance(status, dict) else str(status)
            labels = fields.get("labels", [])
            labels_name = ", ".join(labels) if isinstance(labels, list) else str(labels)
            assignee = fields.get("assignee")
            assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
            
            self.jira_tree.insert("", "end", 
                                 values=(key, created, summary, labels_name, status_name, assignee_name))

        self._autofit_jira_columns()
        self._apply_jira_filter_highlight()

    def _on_jira_filter_changed(self, _event=None):
        """React to typing in JIRA filter entry."""
        self._apply_jira_filter_highlight()

    def _apply_jira_filter_highlight(self):
        """Highlight rows in yellow if any cell contains filter text."""
        needle = self.jira_filter_var.get().strip().lower()
        for item in self.jira_tree.get_children(""):
            values = self.jira_tree.item(item, "values") or ()
            haystack = " ".join(str(v).lower() for v in values)
            if needle and needle in haystack:
                self.jira_tree.item(item, tags=("jira_filter_match",))
            else:
                self.jira_tree.item(item, tags=())

    def _autofit_jira_columns(self):
        """Auto-fit JIRA columns to content and keep Summary visibly widest."""
        cols = ("key", "created", "summary", "labels", "status", "assignee")
        cell_font = tkfont.nametofont("TkDefaultFont")

        widths: dict[str, int] = {}
        for col in cols:
            heading_text = self.jira_tree.heading(col, "text") or col
            max_px = cell_font.measure(str(heading_text)) + 26
            for item in self.jira_tree.get_children(""):
                value = self.jira_tree.set(item, col)
                max_px = max(max_px, cell_font.measure(str(value)) + 20)
            widths[col] = max_px

        # Clamp compact columns; Summary stays larger and can expand.
        caps = {
            "key": (90, 180),
            "created": (120, 190),
            "status": (90, 170),
            "labels": (120, 360),
            "assignee": (120, 260),
        }
        for col, (min_w, max_w) in caps.items():
            widths[col] = max(min_w, min(max_w, widths[col]))

        widest_other = max(widths[c] for c in widths if c != "summary")
        summary_target = max(widths["summary"], int(widest_other * 1.8), 420)
        widths["summary"] = min(summary_target, 1200)

        for col in cols:
            self.jira_tree.column(
                col,
                width=widths[col],
                minwidth=80 if col == "summary" else 60,
                stretch=(col == "summary"),
            )

    def _format_jira_created(self, created_raw: str) -> str:
        """Format JIRA created timestamp to a readable local string."""
        if not created_raw:
            return ""
        try:
            # Example: 2026-03-31T09:47:12.123+0000
            dt = datetime.strptime(created_raw, "%Y-%m-%dT%H:%M:%S.%f%z")
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            # Fallback for unexpected formats.
            return str(created_raw).replace("T", " ")[:16]

    def _sort_jira_column(self, col: str):
        """Sort JIRA table by column."""
        rev = self._jira_sort_reverse.get(col, False)
        data = [(self.jira_tree.set(k, col), k) for k in self.jira_tree.get_children("")]
        data.sort(key=lambda x: x[0].lower(), reverse=rev)
        for idx, (_, k) in enumerate(data):
            self.jira_tree.move(k, "", idx)
        self._jira_sort_reverse[col] = not rev

    def _open_jira_search(self, jql: str):
        """Open JIRA search in browser."""
        base_url = os.getenv("JIRA_BASE_URL", "https://jira.devtools.intel.com")
        url = f"{base_url.rstrip('/')}/issues/?jql={urllib.parse.quote(jql)}"
        webbrowser.open(url)

    def _copy_jira_query(self, jql: str):
        """Copy query to clipboard."""
        self.clipboard_clear()
        self.clipboard_append(jql)
        self.jira_status_label.configure(text="Query copied to clipboard", foreground="gray")

    def _show_jira_ctx(self, event):
        """Show context menu for a row in the JIRA table."""
        item = self.jira_tree.identify_row(event.y)
        if not item:
            return "break"

        self.jira_tree.selection_set(item)
        col_id = self.jira_tree.identify_column(event.x)
        self._jira_ctx_col = int(col_id.lstrip("#")) - 1 if col_id else None

        self._jira_ctx.delete(0, "end")
        self._jira_ctx.add_command(label="Open issue in JIRA",
                                   command=self._open_selected_jira_issue)
        self._jira_ctx.add_separator()
        self._jira_ctx.add_command(label="Copy value", command=self._copy_jira_value)
        self._jira_ctx.add_command(label="Copy row", command=self._copy_jira_row)
        try:
            self._jira_ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._jira_ctx.grab_release()
        return "break"

    def _open_selected_jira_issue(self):
        """Open selected JIRA issue key from the table row in browser."""
        sel = self.jira_tree.selection()
        if not sel:
            return

        values = self.jira_tree.item(sel[0], "values") or ()
        issue_key = str(values[0]).strip() if values else ""
        if not issue_key:
            messagebox.showwarning("No issue key", "Selected row has no issue key.")
            return

        base_url = os.getenv("JIRA_BASE_URL", "https://jira.devtools.intel.com")
        webbrowser.open(f"{base_url.rstrip('/')}/browse/{issue_key}")

    def _copy_jira_value(self):
        """Copy selected JIRA table cell value to clipboard."""
        sel = self.jira_tree.selection()
        if sel and self._jira_ctx_col is not None:
            vals = self.jira_tree.item(sel[0], "values")
            if 0 <= self._jira_ctx_col < len(vals):
                self.clipboard_clear()
                self.clipboard_append(vals[self._jira_ctx_col])

    def _copy_jira_row(self):
        """Copy selected JIRA table row to clipboard."""
        sel = self.jira_tree.selection()
        if sel:
            vals = self.jira_tree.item(sel[0], "values")
            self.clipboard_clear()
            self.clipboard_append("\t".join(vals))

    # ---------------------------------------------------------- helpers ------

    def _combo(self, parent, values, default, row, col, width=22):
        cb = ttk.Combobox(parent, values=values, width=width, state="readonly")
        cb.set(default)
        cb.grid(row=row, column=col, padx=8, pady=3, sticky="w")
        return cb

    def _op(self, combo_value: str) -> str:
        """Convert display value like '~= (regex/contains)' → '~='"""
        return combo_value.split()[0]

    def _check_deps(self):
        if not HAS_REQUESTS:
            messagebox.showwarning(
                "Missing dependency",
                "Module 'requests' is not installed.\n\n"
                "Run in your terminal:\n\n"
                "  pip install requests beautifulsoup4\n\n"
                "The application requires this to fetch data."
            )
        elif not HAS_BS4:
            self._set_status(
                "Tip: install beautifulsoup4 for best results  (pip install beautifulsoup4)",
                warn=True
            )

    # ----------------------------------------------------- query building ---

    def _build_query(self) -> str:
        parts = []

        tv = self.test_value.get().strip()
        if tv:
            parts.append(f"test_name{self._op(self.test_match.get())}'{tv}'")

        mv = self.machine_value.get().strip()
        if mv:
            conn = self.machine_conn.get()
            expr = f"machine_name{self._op(self.machine_match.get())}'{mv}'"
            parts.append(f"{conn} {expr}" if parts else
                         (f"NOT {expr}" if "NOT" in conn else expr))

        rv = self.rc_value.get().strip()
        if rv:
            conn = self.rc_conn.get()
            expr = f"runconfig_name{self._op(self.rc_match.get())}'{rv}'"
            parts.append(f"{conn} {expr}" if parts else
                         (f"NOT {expr}" if "NOT" in conn else expr))

        dv = self.date_value.get().strip()
        if dv:
            expr = f"runconfig_added_on > datetime({dv})"
            parts.append(f"AND {expr}" if parts else expr)

        return " ".join(parts)

    def _update_preview(self, _=None):
        # Only overwrite when the entry is not being manually edited
        self.query_var.set(self._build_query())

    def _on_query_edit(self, _=None):
        """User typed manually in the preview box — don't auto-parse."""
        pass

    def _on_query_paste(self, _=None):
        """After paste: parse only when all filter fields are empty."""
        all_empty = not any([
            self.test_value.get().strip(),
            self.machine_value.get().strip(),
            self.rc_value.get().strip(),
            self.date_value.get().strip(),
        ])
        if all_empty:
            self.after(10, self._parse_query_to_fields)

    def _parse_query_to_fields(self):
        """Parse the raw query string back into the individual filter fields."""
        raw = self.query_var.get().strip()
        if not raw:
            return

        # test_name
        tm = re.search(r"test_name\s*(~?=)\s*'([^']*)'", raw, re.IGNORECASE)
        if tm:
            self.test_match.set(
                "~= (regex/contains)" if "~" in tm.group(1) else "= (exact)")
            self.test_value.delete(0, "end")
            self.test_value.insert(0, tm.group(2))

        # machine_name
        mm = re.search(
            r"(AND\s+NOT|AND)\s+machine_name\s*(~?=)\s*'([^']*)'|"
            r"^machine_name\s*(~?=)\s*'([^']*)'",
            raw, re.IGNORECASE)
        if mm:
            if mm.group(1):                           # matched with connector
                conn = "AND NOT" if "NOT" in mm.group(1).upper() else "AND"
                op   = mm.group(2)
                val  = mm.group(3)
            else:                                     # first token, no connector
                conn = "AND"
                op   = mm.group(4)
                val  = mm.group(5)
            self.machine_conn.set(conn)
            self.machine_match.set(
                "~= (regex/contains)" if op and "~" in op else "= (exact)")
            self.machine_value.delete(0, "end")
            self.machine_value.insert(0, val)

        # runconfig_name
        rm = re.search(
            r"(AND\s+NOT|AND)\s+runconfig_name\s*(~?=)\s*'([^']*)'|"
            r"^runconfig_name\s*(~?=)\s*'([^']*)'",
            raw, re.IGNORECASE)
        if rm:
            if rm.group(1):
                conn = "AND NOT" if "NOT" in rm.group(1).upper() else "AND"
                op   = rm.group(2)
                val  = rm.group(3)
            else:
                conn = "AND"
                op   = rm.group(4)
                val  = rm.group(5)
            self.rc_conn.set(conn)
            self.rc_match.set(
                "~= (regex/contains)" if op and "~" in op else "= (exact)")
            self.rc_value.delete(0, "end")
            self.rc_value.insert(0, val)

        # date
        dm = re.search(r"runconfig_added_on\s*>\s*datetime\(([^)]+)\)", raw, re.IGNORECASE)
        self.date_value.delete(0, "end")
        if dm:
            self.date_value.insert(0, dm.group(1).strip())

        # Rebuild preview from parsed fields to normalise it
        self._update_preview()
        self._set_status("Query parsed into fields.")

    def _copy_query(self):
        self.clipboard_clear()
        self.clipboard_append(self._build_query())
        self._set_status("Query copied to clipboard.")

    def _open_browser(self):
        q = self._build_query()
        if q:
            webbrowser.open(self._get_cibuglog_results_base() + "?query=" + urllib.parse.quote(q))

    def _clear_all(self):
        for w in (self.test_value, self.machine_value, self.rc_value, self.date_value):
            w.delete(0, "end")
        self.test_match.set("= (exact)")
        self.machine_conn.set("AND")
        self.machine_match.set("~= (regex/contains)")
        self.rc_conn.set("AND NOT")
        self.rc_match.set("~= (regex/contains)")
        self._update_preview()
        self._clear_table()
        self.count_var.set("")
        self._set_status("Ready")

    def _clear_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._item_urls = {}
        self._item_external_url = {}

    # -------------------------------------------------------- fetch / parse --

    def _load_history(self):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            self._query_history[:] = data.get("queries", [])[:20]
            for key in ("test", "machine", "runconfig", "date"):
                self._field_history[key] = data.get(key, [])[:20]
            saved_root = data.get("cibuglog_root", "")
            if saved_root in CIBUGLOG_ROOT_OPTIONS:
                self.cibuglog_root_var.set(saved_root)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        self.test_value.configure(values=self._field_history["test"])
        self.machine_value.configure(values=self._field_history["machine"])
        self.rc_value.configure(values=self._field_history["runconfig"])
        self.date_value.configure(values=self._field_history["date"])

    def _save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "queries":      self._query_history,
                    "test":         self._field_history["test"],
                    "machine":      self._field_history["machine"],
                    "runconfig":    self._field_history["runconfig"],
                    "date":         self._field_history["date"],
                    "cibuglog_root": self.cibuglog_root_var.get(),
                }, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _add_to_history(self, query: str):
        def _push(lst, val):
            if val in lst:
                lst.remove(val)
            lst.insert(0, val)
            del lst[20:]

        _push(self._query_history, query)
        for key, widget in (
            ("test",      self.test_value),
            ("machine",   self.machine_value),
            ("runconfig", self.rc_value),
            ("date",      self.date_value),
        ):
            val = widget.get().strip()
            if val:
                _push(self._field_history[key], val)
                widget.configure(values=self._field_history[key])
        self._save_history()

    def _refresh_history_dropdown(self):
        self.query_entry.configure(values=self._query_history)

    def _on_history_select(self, _event=None):
        self._parse_query_to_fields()

    def _fetch_async(self):
        if not HAS_REQUESTS:
            messagebox.showerror("Missing dependency",
                                 "Run: pip install requests beautifulsoup4")
            return
        q = self._build_query()
        if not q:
            messagebox.showwarning("Empty query",
                                   "Please fill in at least one filter field.")
            return
        self._update_preview()
        self._add_to_history(q)
        self._clear_table()
        self.count_var.set("")
        self._set_status("Fetching …")
        self.progress.start(10)
        threading.Thread(target=self._worker, args=(q,), daemon=True).start()

    def _worker(self, query: str):
        import traceback
        try:
            url = self._get_cibuglog_results_base() + "?" + urllib.parse.urlencode(
                {"query": query, "page": 1, "page_size": PAGE_SIZE}
            )
            auth = HttpNegotiateAuth() if HAS_SSPI else None

            # --- first attempt (with or without proxy as chosen) ---
            proxies = PROXIES if self.use_proxy_var.get() else None
            kwargs  = dict(timeout=30, proxies=proxies, verify=False, auth=auth)
            resp = requests.get(url, **kwargs)

            # --- if 403/401, retry with the opposite proxy setting ---
            if resp.status_code in (401, 403):
                alt_proxies = None if proxies else PROXIES
                resp2 = requests.get(url, timeout=30, proxies=alt_proxies,
                                     verify=False, auth=auth)
                if resp2.status_code == 200:
                    # update checkbox to reflect what worked
                    self.after(0, self.use_proxy_var.set, alt_proxies is not None)
                    resp = resp2

            resp.raise_for_status()
            count, rows, url_lists, external_urls = self._parse(resp.text)
            self.after(0, self._populate, count, rows, url_lists, external_urls)
        except requests.exceptions.ConnectionError as exc:
            self.after(0, self._on_error,
                       f"Connection failed.\n{exc}\n\n"
                       "Make sure you are connected to the Intel network (VPN).")
        except requests.exceptions.Timeout:
            self.after(0, self._on_error, "Request timed out (30 s).")
        except requests.exceptions.HTTPError as exc:
            self.after(0, self._on_error,
                       f"HTTP {exc.response.status_code} - {exc.response.reason}\n"
                       f"URL: {exc.response.url}\n\n"
                       f"Try toggling the 'Use proxy' checkbox and retry.")
        except Exception as exc:
            self.after(0, self._on_error,
                       f"Unexpected error:\n{type(exc).__name__}: {exc}\n\n"
                       f"{traceback.format_exc()}")

    def _parse(self, html: str):
        count = 0
        m = re.search(r"Results list\s*\(\s*(\d+)\s*\)", html)
        if m:
            count = int(m.group(1))

        rows = []
        url_lists = []   # parallel list: URLs extracted from issue cell per row
        external_urls = []  # parallel list: URL labeled as "external URL"
        if HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table"):
                for tr in table.find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) >= 5:
                        row = [re.sub(r"\s+", " ", td.get_text(" ", strip=True))
                               for td in tds[:7]]
                        while len(row) < 7:
                            row.append("")
                        rows.append(row)
                        # collect hrefs from the issue cell (last one, index 6)
                        issue_td = tds[6] if len(tds) > 6 else tds[-1]
                        urls = [a["href"] for a in issue_td.find_all("a", href=True)]
                        url_lists.append(urls)
                        ext_url = ""
                        for a in issue_td.find_all("a", href=True):
                            around = []
                            for sib in (a.previous_sibling, a.next_sibling):
                                if sib is None:
                                    continue
                                if hasattr(sib, "get_text"):
                                    s_txt = sib.get_text(" ", strip=True)
                                else:
                                    s_txt = str(sib).strip()
                                if s_txt:
                                    around.append(s_txt)
                            markers = [
                                a.get_text(" ", strip=True),
                                a.get("title", ""),
                                a.get("aria-label", ""),
                                a.get("data-original-title", ""),
                                " ".join(a.get("class", [])),
                                " ".join(around),
                            ]
                            if any(_is_external_link_marker(m) for m in markers):
                                ext_url = a["href"]
                                break
                        if not ext_url:
                            for u in urls:
                                if _looks_like_tree_url(u):
                                    ext_url = u
                                    break
                        external_urls.append(ext_url)
        else:
            # Regex fallback
            for tr_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                cells_raw = list(re.finditer(
                    r"<td[^>]*>(.*?)</td>", tr_m.group(1), re.S | re.I))
                if len(cells_raw) < 5:
                    continue
                cells = [
                    re.sub(r"\s+", " ",
                           re.sub(r"<[^>]+>", " ", c.group(1))).strip()
                    for c in cells_raw
                ]
                while len(cells) < 7:
                    cells.append("")
                rows.append(cells[:7])
                # extract hrefs from raw issue cell html
                issue_raw = cells_raw[6].group(1) if len(cells_raw) > 6 else ""
                urls = re.findall(r'href=["\']([^"\'>]+)["\']', issue_raw, re.I)
                url_lists.append(urls)
                ext_url = ""
                for a_m in re.finditer(
                    r"<a([^>]*)href=[\"']([^\"'>]+)[\"']([^>]*)>(.*?)</a>",
                    issue_raw,
                    re.I | re.S,
                ):
                    start, end = a_m.span()
                    attrs = f"{a_m.group(1)} {a_m.group(3)}"
                    label = re.sub(r"<[^>]+>", " ", a_m.group(4))
                    label = re.sub(r"\s+", " ", label).strip()
                    nearby_after = re.sub(r"<[^>]+>", " ", issue_raw[end:end + 140])
                    nearby_before = re.sub(r"<[^>]+>", " ", issue_raw[max(0, start - 140):start])
                    nearby = re.sub(r"\s+", " ", f"{nearby_before} {nearby_after}").strip()
                    attr_markers = " ".join(re.findall(
                        r"(?:title|aria-label|data-original-title|class)\s*=\s*[\"']([^\"']*)[\"']",
                        attrs,
                        re.I,
                    ))
                    if (
                        _is_external_link_marker(label)
                        or _is_external_link_marker(attr_markers)
                        or _is_external_link_marker(nearby)
                    ):
                        ext_url = a_m.group(2)
                        break
                if not ext_url:
                    for u in urls:
                        if _looks_like_tree_url(u):
                            ext_url = u
                            break
                external_urls.append(ext_url)

        return count, rows, url_lists, external_urls

    def _populate(
        self,
        count: int,
        rows: list,
        url_lists: list | None = None,
        external_urls: list | None = None,
    ):
        self.progress.stop()
        self._clear_table()
        self._item_urls: dict[str, list[str]] = {}
        self._item_external_url: dict[str, str] = {}

        if not rows:
            self._set_status("No results found." if count == 0 else
                             f"{count} results, but table could not be parsed.")
            self.count_var.set(f"Total: {count}  |  Loaded: 0")
            return

        self.count_var.set(
            f"Total: {count}  |  Showing: {len(rows)}  "
            f"(page 1, max {PAGE_SIZE} per page)"
        )
        self._set_status(f"Done — {len(rows)} rows loaded.")

        for i, row in enumerate(rows):
            status_raw = row[3] if len(row) > 3 else ""
            tag = classify_status(status_raw)

            display = [clean_cell(c) for c in row[:7]]
            while len(display) < 7:
                display.append("")

            # build tree URL before removing duration (display[5] = build/runconfig)
            if _is_external_link_marker(status_raw):
                tree_url = _build_tree_url_from_row(
                    display[0],
                    display[1],
                    display[5],
                    self._get_cibuglog_origin(),
                    display[2],
                )

            # drop duration (index 4) — not shown in table
            display_row = display[:4] + display[5:]

            iid = self.tree.insert("", "end", values=display_row,
                                   tags=(tag,) if tag else ())
            if url_lists and i < len(url_lists):
                self._item_urls[iid] = url_lists[i]

            if external_urls and i < len(external_urls) and external_urls[i]:
                existing = self._item_external_url.get(iid, "")
                candidate = external_urls[i]
                if not existing:
                    self._item_external_url[iid] = candidate
                elif _looks_like_tree_url(candidate):
                    self._item_external_url[iid] = candidate

            # Fallback to deterministic /tree URL only if parsing did not provide one.
            if _is_external_link_marker(status_raw) and tree_url:
                if not self._item_external_url.get(iid):
                    self._item_external_url[iid] = tree_url

    def _on_error(self, msg: str):
        self.progress.stop()
        self._set_status(f"Error: {msg.splitlines()[0]}", error=True)
        # Selectable error dialog (so user can copy the text)
        dlg = tk.Toplevel(self)
        dlg.title("Fetch Error")
        dlg.resizable(True, True)
        dlg.grab_set()
        txt = tk.Text(dlg, wrap="word", font=("Consolas", 9),
                      width=80, height=18, relief="flat",
                      background="#fff0f0", foreground="#721c24")
        txt.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        txt.insert("1.0", msg)
        txt.configure(state="disabled")
        sb = ttk.Scrollbar(dlg, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=(4, 10))
        dlg.bind("<Escape>", lambda _: dlg.destroy())

    # ---------------------------------------------------------- table utils --

    def _sort_column(self, col: str):
        rev = self._sort_reverse.get(col, False)
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        data.sort(key=lambda x: x[0].lower(), reverse=rev)
        for idx, (_, k) in enumerate(data):
            self.tree.move(k, "", idx)
        self._sort_reverse[col] = not rev
        arrow = " ↑" if rev else " ↓"
        col_cfg = {
            "test": "Test Name", "runconfig": "Machine", "tags": "Tags",
            "status": "Status",
            "build": "Run Config", "issue": "Issue",
        }
        for c, lbl in col_cfg.items():
            self.tree.heading(c, text=lbl + (arrow if c == col else ""))

    def _show_ctx(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return "break"
        self.tree.selection_set(item)
        col_id = self.tree.identify_column(event.x)
        self._ctx_col = int(col_id.lstrip("#")) - 1 if col_id else None

        # Rebuild menu each time
        self._ctx.delete(0, "end")
        self._ctx.add_command(label="Copy value", command=self._copy_value)
        self._ctx.add_command(label="Copy row",   command=self._copy_row)

        jira_base = "https://jira.devtools.intel.com"
        cibuglog_base = self._get_cibuglog_origin()
        ext_raw = getattr(self, "_item_external_url", {}).get(item, "").strip()

        # Strong fallback: infer external link from all row URLs.
        if not ext_raw:
            normalized_candidates = []
            for u in getattr(self, "_item_urls", {}).get(item, []):
                nu = _normalize_result_url(u, jira_base, cibuglog_base)
                if nu:
                    normalized_candidates.append(nu)

            # Also scan visible row values for plain URLs.
            vals = self.tree.item(item, "values") or ()
            text_blob = " ".join(str(v) for v in vals)
            for m in re.findall(r"https?://[^\s\]\)>'\"]+", text_blob, re.I):
                normalized_candidates.append(m)

            seen = set()
            normalized_candidates = [u for u in normalized_candidates
                                     if not (u in seen or seen.add(u))]

            tree_candidates = [u for u in normalized_candidates if _looks_like_tree_url(u)]
            if tree_candidates:
                ext_raw = tree_candidates[0]

            preferred = []
            internal = []
            for u in normalized_candidates:
                lu = u.lower()
                if "jira.devtools.intel.com" in lu or "gfx-ci-internal.igk.intel.com" in lu:
                    internal.append(u)
                else:
                    preferred.append(u)

            if not ext_raw and preferred:
                ext_raw = preferred[0]
            elif not ext_raw and internal:
                ext_raw = internal[0]

        if ext_raw:
            ext_url = _normalize_result_url(ext_raw, jira_base, cibuglog_base)
            self._ctx.add_separator()
            self._ctx.add_command(
                label="Open external URL",
                command=lambda x=ext_url: webbrowser.open(x),
            )

        # Collect URLs for this row
        raw_urls = getattr(self, "_item_urls", {}).get(item, [])
        urls = []
        for u in raw_urls:
            nu = _normalize_result_url(u, jira_base, cibuglog_base)
            if nu:
                urls.append(nu)
        seen = set()
        urls = [u for u in urls if not (u in seen or seen.add(u))]

        # Search for Jira ticket IDs in ALL columns of the row
        all_values = self.tree.item(item, "values") or []
        combined = " ".join(str(v) for v in all_values) + " " + " ".join(urls)
        jira_tickets = re.findall(r"(?<![A-Z])([A-Z]{2,}-\d+)", combined)
        for ticket in dict.fromkeys(jira_tickets):   # deduplicate, preserve order
            jira_url = f"{jira_base}/browse/{ticket}"
            if jira_url not in urls:
                urls.append(jira_url)

        if urls:
            self._ctx.add_separator()
            for u in urls:
                if "jira" in u or "/browse/" in u:
                    label = "Open Jira: " + u.split("/")[-1]
                else:
                    label = "Open URL: " + u
                self._ctx.add_command(label=label,
                                      command=lambda x=u: webbrowser.open(x))

        try:
            self._ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx.grab_release()
        return "break"

    def _copy_value(self):
        sel = self.tree.selection()
        if sel and self._ctx_col is not None:
            vals = self.tree.item(sel[0], "values")
            if 0 <= self._ctx_col < len(vals):
                self.clipboard_clear()
                self.clipboard_append(vals[self._ctx_col])

    def _copy_row(self):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            self.clipboard_clear()
            self.clipboard_append("\t".join(vals))

    def _open_issue(self):
        pass  # handled dynamically via context menu

    def _get_cibuglog_root(self) -> str:
        return (self.cibuglog_root_var.get() or CIBUGLOG_ROOT_OPTIONS[1]).rstrip("/")

    def _get_cibuglog_results_base(self) -> str:
        return self._get_cibuglog_root() + "/results/all"

    def _get_cibuglog_origin(self) -> str:
        root = self._get_cibuglog_root()
        parts = urllib.parse.urlsplit(root)
        return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else root

    def _export_csv(self):
        rows = [self.tree.item(child, "values")
                for child in self.tree.get_children()]
        if not rows:
            messagebox.showinfo("Export", "No data to export.")
            return
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Test Name", "Machine", "Tags",
                         "Status", "Run Config", "Issue"])
        writer.writerows(rows)
        self.clipboard_clear()
        self.clipboard_append(buf.getvalue())
        self._set_status(f"CSV ({len(rows)} rows) copied to clipboard — paste into Excel or a file.")

    # ---------------------------------------------------------------- misc --

    def _set_status(self, msg: str, error: bool = False, warn: bool = False):
        self.status_var.set(msg)
        color = "red" if error else ("#b8860b" if warn else "gray")
        self.status_lbl.configure(foreground=color)


if __name__ == "__main__":
    app = CIBugLogApp()
    app.mainloop()
