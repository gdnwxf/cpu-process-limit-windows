from __future__ import annotations

import ntpath
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from cpu_process_limit_windows.config import (
    UserConfig,
    load_config,
    process_config_key,
    save_config,
)
from cpu_process_limit_windows.core import CpuLimitSession, Win32Error, limit_existing_process
from cpu_process_limit_windows.process_metrics import (
    calculate_cpu_percent,
    get_process_cpu_time,
)
from cpu_process_limit_windows.process_list import ProcessInfo, fuzzy_match, list_processes
from cpu_process_limit_windows.settings import SETTINGS, parse_cpu_percent
from cpu_process_limit_windows.tray import TrayController, TrayUnavailable


class CpuLimiterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CPU 进程限制器")
        self.geometry(f"{SETTINGS.window_width}x{SETTINGS.window_height}")
        self.minsize(980, 560)

        self.config: UserConfig = load_config()
        self.auto_limit_failures: set[str] = set()

        self.cpu_var = tk.StringVar(value=f"{self.config.default_cpu_percent:g}")
        self.active_search_var = tk.StringVar()
        self.limited_search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")

        self.active_processes: dict[str, ProcessInfo] = {}
        self.sessions: dict[str, CpuLimitSession] = {}
        self.limited_sources: dict[str, ProcessInfo] = {}
        self.cpu_samples: dict[str, tuple[float, float]] = {}
        self.cpu_usage: dict[str, float] = {}
        self.active_sort_column = "usage"
        self.active_sort_desc = True
        self.limited_sort_column = "status"
        self.limited_sort_desc = False
        self.heading_drag: dict[str, object] | None = None
        self.panel_resize: dict[str, object] | None = None
        self.exiting = False
        self.tray = TrayController(
            on_show=lambda: self.after(0, self._restore_from_tray),
            on_exit=lambda: self.after(0, self._exit_from_tray),
        )

        self._build_layout()
        self._bind_events()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self._refresh_processes()
        self._sync_limited_processes()

    def _build_layout(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        settings = ttk.Frame(root)
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        settings.columnconfigure(5, weight=1)

        ttk.Label(settings, text="全局/默认 CPU 限制 (%)").grid(row=0, column=0, sticky="w")
        self.cpu_entry = ttk.Entry(settings, textvariable=self.cpu_var, width=10)
        self.cpu_entry.grid(
            row=0,
            column=1,
            sticky="w",
            padx=(10, 18),
        )
        ttk.Label(settings, textvariable=self.status_var).grid(
            row=0,
            column=5,
            sticky="e",
        )

        content = ttk.Frame(root)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1, minsize=360, uniform="process_panels")
        content.columnconfigure(2, weight=0, minsize=170)
        content.columnconfigure(4, weight=1, minsize=360, uniform="process_panels")
        content.rowconfigure(0, weight=1)
        self.content = content
        self.after_idle(self._reset_equal_panel_widths)

        active_frame = ttk.LabelFrame(content, text="活动进程", padding=10)
        active_frame.grid(row=0, column=0, sticky="nsew")
        active_frame.columnconfigure(0, weight=1)
        active_frame.rowconfigure(1, weight=1)
        self.active_frame = active_frame

        ttk.Entry(active_frame, textvariable=self.active_search_var).grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )
        self.active_table = self._create_process_table(active_frame)
        self.active_table.grid(row=1, column=0, sticky="nsew")
        active_y_scrollbar = ttk.Scrollbar(
            active_frame,
            orient=tk.VERTICAL,
            command=self.active_table.yview,
        )
        active_y_scrollbar.grid(row=1, column=1, sticky="ns")
        active_x_scrollbar = ttk.Scrollbar(
            active_frame,
            orient=tk.HORIZONTAL,
            command=self.active_table.xview,
        )
        active_x_scrollbar.grid(row=2, column=0, sticky="ew")
        self.active_table.configure(
            xscrollcommand=active_x_scrollbar.set,
            yscrollcommand=active_y_scrollbar.set,
        )

        left_grip = ttk.Frame(content, width=8, cursor="sb_h_double_arrow")
        left_grip.grid(row=0, column=1, sticky="ns")
        left_grip.bind("<ButtonPress-1>", self._start_panel_resize)
        left_grip.bind("<B1-Motion>", self._drag_panel_resize)

        buttons = ttk.Frame(content, padding=(14, 0), width=170, cursor="sb_h_double_arrow")
        buttons.grid(row=0, column=2, sticky="ns")
        buttons.rowconfigure(0, weight=1)
        buttons.rowconfigure(3, weight=1)
        buttons.columnconfigure(0, weight=1)
        buttons.grid_propagate(False)
        buttons.bind("<ButtonPress-1>", self._start_panel_resize)
        buttons.bind("<B1-Motion>", self._drag_panel_resize)
        self.add_button = ttk.Button(
            buttons,
            text=self._add_button_text(),
            command=self._limit_selected_with_default,
            width=14,
        )
        self.add_button.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(
            buttons,
            text="< 解除",
            command=self._release_selected_limited,
            width=14,
        ).grid(row=2, column=0, sticky="ew")

        right_grip = ttk.Frame(content, width=8, cursor="sb_h_double_arrow")
        right_grip.grid(row=0, column=3, sticky="ns")
        right_grip.bind("<ButtonPress-1>", self._start_panel_resize)
        right_grip.bind("<B1-Motion>", self._drag_panel_resize)

        limited_frame = ttk.LabelFrame(content, text="限制的进程", padding=10)
        limited_frame.grid(row=0, column=4, sticky="nsew")
        limited_frame.columnconfigure(0, weight=1)
        limited_frame.rowconfigure(1, weight=1)
        self.limited_frame = limited_frame

        ttk.Entry(limited_frame, textvariable=self.limited_search_var).grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )
        self.limited_table = self._create_process_table(limited_frame, limited=True)
        self.limited_table.grid(row=1, column=0, sticky="nsew")
        limited_y_scrollbar = ttk.Scrollbar(
            limited_frame,
            orient=tk.VERTICAL,
            command=self.limited_table.yview,
        )
        limited_y_scrollbar.grid(row=1, column=1, sticky="ns")
        limited_x_scrollbar = ttk.Scrollbar(
            limited_frame,
            orient=tk.HORIZONTAL,
            command=self.limited_table.xview,
        )
        limited_x_scrollbar.grid(row=2, column=0, sticky="ew")
        self.limited_table.configure(
            xscrollcommand=limited_x_scrollbar.set,
            yscrollcommand=limited_y_scrollbar.set,
        )

    def _create_process_table(
        self,
        parent: ttk.Frame,
        limited: bool = False,
    ) -> ttk.Treeview:
        columns = (
            ("pid", "name", "limit", "usage", "status", "path")
            if limited
            else ("usage", "pid", "name", "path")
        )
        table = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        table.column("pid", width=90, anchor=tk.CENTER, stretch=False)
        table.column("name", width=170, stretch=False)
        table.column("path", width=720, stretch=False)
        table.column("usage", width=110, anchor=tk.CENTER, stretch=False)
        if limited:
            table.column("limit", width=90, anchor=tk.CENTER, stretch=False)
            table.column("status", width=90, anchor=tk.CENTER, stretch=False)
            headings = {
                "pid": "PID",
                "name": "进程名",
                "limit": "限制 %",
                "usage": "当前 CPU %",
                "status": "状态",
                "path": "路径",
            }
            for column, text in headings.items():
                table.heading(column, text=text)
        else:
            headings = {
                "pid": "PID",
                "name": "进程名",
                "usage": "当前 CPU %",
                "path": "路径",
            }
            for column, text in headings.items():
                table.heading(column, text=text)
        return table

    def _bind_events(self) -> None:
        self.cpu_var.trace_add("write", lambda *_: self._refresh_add_button_text())
        self.cpu_entry.bind("<FocusOut>", lambda _event: self._save_default_cpu())
        self.cpu_entry.bind("<Return>", lambda _event: self._save_default_cpu())
        self.active_search_var.trace_add("write", lambda *_: self._render_active())
        self.limited_search_var.trace_add("write", lambda *_: self._render_limited())
        self.active_table.bind("<Button-3>", self._show_active_menu)
        self.limited_table.bind("<Button-3>", self._show_limited_menu)
        self.active_table.bind("<ButtonPress-1>", self._start_heading_drag)
        self.limited_table.bind("<ButtonPress-1>", self._start_heading_drag)
        self.active_table.bind("<B1-Motion>", self._track_heading_drag)
        self.limited_table.bind("<B1-Motion>", self._track_heading_drag)
        self.active_table.bind("<ButtonRelease-1>", self._finish_heading_drag)
        self.limited_table.bind("<ButtonRelease-1>", self._finish_heading_drag)
        self.active_table.bind("<Double-1>", self._handle_active_double_click)
        self.limited_table.bind("<Delete>", lambda _event: self._release_selected_limited())

    def _refresh_processes(self) -> None:
        try:
            processes = list_processes()
        except Win32Error as exc:
            self.status_var.set("无法读取进程列表")
            messagebox.showerror("进程列表错误", str(exc), parent=self)
            return

        self.active_processes = {
            str(process.pid): process
            for process in processes
            if str(process.pid) not in self.sessions
        }
        self._update_active_cpu_usage()
        self._apply_saved_limits_to_active_processes()
        self._render_active()
        self.after(SETTINGS.process_refresh_interval_ms, self._refresh_processes)

    def _apply_saved_limits_to_active_processes(self) -> None:
        applied = 0
        for item_id, process in list(self.active_processes.items()):
            key = self._process_key(process)
            if not key or key not in self.config.process_limits:
                continue
            if key in self.auto_limit_failures:
                continue

            cpu_percent = self.config.process_limits[key]
            try:
                session = limit_existing_process(process.pid, cpu_percent)
            except Win32Error:
                self.auto_limit_failures.add(key)
                continue

            self.sessions[item_id] = session
            self.limited_sources[item_id] = process
            self.active_processes.pop(item_id, None)
            applied += 1

        if applied:
            self.status_var.set(f"已根据配置自动限制 {applied} 个活动进程。")

    def _sync_limited_processes(self) -> None:
        for item_id, session in list(self.sessions.items()):
            try:
                exit_code = session.wait(0)
            except Win32Error:
                exit_code = -1
            if exit_code is not None:
                session.close()
                self.sessions.pop(item_id, None)
                self.limited_sources.pop(item_id, None)
                self.cpu_samples.pop(item_id, None)
                self.cpu_usage.pop(item_id, None)
                self.status_var.set(f"PID {item_id} 已退出，退出码 {exit_code}。")
                continue

            self._update_cpu_usage(item_id, session.pid)

        self._render_limited()
        self._render_active()
        self.after(SETTINGS.poll_interval_ms, self._sync_limited_processes)

    def _render_active(self) -> None:
        selected = set(self.active_table.selection())
        self.active_table.delete(*self.active_table.get_children())
        query = self.active_search_var.get()

        processes = list(self.active_processes.items())
        processes.sort(
            key=lambda item: self._active_sort_value(item[1], self.active_sort_column),
            reverse=self.active_sort_desc,
        )

        for item_id, process in processes:
            if item_id in self.sessions:
                continue
            usage = self.cpu_usage.get(item_id)
            usage_text = "--" if usage is None else f"{usage:.1f}"
            searchable_text = f"{process.searchable_text} {usage_text}"
            if not fuzzy_match(query, searchable_text):
                continue
            self.active_table.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    usage_text,
                    process.pid,
                    process.name,
                    process.path,
                ),
            )

        self._restore_selection(self.active_table, selected)

    def _render_limited(self) -> None:
        selected = set(self.limited_table.selection())
        self.limited_table.delete(*self.limited_table.get_children())
        query = self.limited_search_var.get()

        rows = self._limited_rows()
        rows.sort(
            key=lambda row: self._limited_sort_value(row, self.limited_sort_column),
            reverse=self.limited_sort_desc,
        )

        for row in rows:
            searchable_text = (
                f"{row['pid']} {row['name']} {row['limit']} "
                f"{row['usage']} {row['status']} {row['path']}"
            )
            if not fuzzy_match(query, searchable_text):
                continue
            self.limited_table.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                values=(
                    row["pid"],
                    row["name"],
                    row["limit"],
                    row["usage"],
                    row["status"],
                    row["path"],
                ),
            )

        self._restore_selection(self.limited_table, selected)

    def _limited_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        active_keys: set[str] = set()

        for item_id, session in self.sessions.items():
            process = self.limited_sources.get(item_id)
            name = process.name if process else ""
            path = process.path if process else session.command_line or ""
            key = self._process_key(process) if process else ""
            if key:
                active_keys.add(key)
            usage = self.cpu_usage.get(item_id)
            rows.append(
                {
                    "id": item_id,
                    "pid": session.pid,
                    "name": name,
                    "limit": f"{session.cpu_percent:g}",
                    "usage": "--" if usage is None else f"{usage:.1f}",
                    "status": "运行中",
                    "path": path,
                }
            )

        for key, cpu_percent in self.config.process_limits.items():
            if key in active_keys:
                continue
            name, path = self._display_from_config_key(key)
            rows.append(
                {
                    "id": self._config_row_id(key),
                    "pid": "",
                    "name": name,
                    "limit": f"{cpu_percent:g}",
                    "usage": "--",
                    "status": "未启动",
                    "path": path,
                }
            )

        return rows

    def _restore_selection(self, table: ttk.Treeview, selected: set[str]) -> None:
        existing = [item_id for item_id in selected if table.exists(item_id)]
        if existing:
            table.selection_set(existing)

    def _set_active_sort(self, column: str) -> None:
        if self.active_sort_column == column:
            self.active_sort_desc = not self.active_sort_desc
        else:
            self.active_sort_column = column
            self.active_sort_desc = False
        self._render_active()

    def _set_limited_sort(self, column: str) -> None:
        if self.limited_sort_column == column:
            self.limited_sort_desc = not self.limited_sort_desc
        else:
            self.limited_sort_column = column
            self.limited_sort_desc = False
        self._render_limited()

    def _start_panel_resize(self, event: tk.Event) -> None:
        self.content.columnconfigure(0, uniform="")
        self.content.columnconfigure(4, uniform="")
        self.panel_resize = {
            "x": event.x_root,
            "active_width": self.active_frame.winfo_width(),
            "limited_width": self.limited_frame.winfo_width(),
        }

    def _drag_panel_resize(self, event: tk.Event) -> None:
        if not self.panel_resize:
            return

        delta = event.x_root - int(self.panel_resize["x"])
        active_width = max(260, int(self.panel_resize["active_width"]) + delta)
        limited_width = max(260, int(self.panel_resize["limited_width"]) - delta)
        self.content.columnconfigure(0, minsize=active_width)
        self.content.columnconfigure(4, minsize=limited_width)

    def _reset_equal_panel_widths(self) -> None:
        self.update_idletasks()
        content_width = self.content.winfo_width()
        middle_width = 170 + 8 + 8
        side_width = max(360, (content_width - middle_width) // 2)
        self.content.columnconfigure(0, minsize=side_width, uniform="process_panels")
        self.content.columnconfigure(4, minsize=side_width, uniform="process_panels")

    def _start_heading_drag(self, event: tk.Event) -> None:
        table = event.widget
        if not isinstance(table, ttk.Treeview):
            return
        if table.identify_region(event.x, event.y) != "heading":
            self.heading_drag = None
            return

        column = table.identify_column(event.x)
        column_id = self._tree_column_id(table, column)
        if not column_id:
            self.heading_drag = None
            return

        self.heading_drag = {
            "table": table,
            "column": column_id,
            "x": event.x,
            "moved": False,
        }

    def _track_heading_drag(self, event: tk.Event) -> None:
        if not self.heading_drag:
            return
        if abs(event.x - int(self.heading_drag["x"])) >= 8:
            self.heading_drag["moved"] = True

    def _finish_heading_drag(self, event: tk.Event) -> None:
        if not self.heading_drag:
            return

        table = self.heading_drag["table"]
        source = str(self.heading_drag["column"])
        moved = bool(self.heading_drag["moved"])
        self.heading_drag = None

        if not isinstance(table, ttk.Treeview):
            return
        if table.identify_region(event.x, event.y) != "heading":
            return

        target = self._tree_column_id(table, table.identify_column(event.x))
        if not target:
            return

        if moved and source != target:
            self._move_display_column(table, source, target)
            return

        if table is self.active_table:
            self._set_active_sort(source)
        elif table is self.limited_table:
            self._set_limited_sort(source)

    def _tree_column_id(self, table: ttk.Treeview, column: str) -> str | None:
        if not column.startswith("#"):
            return None
        index = int(column[1:]) - 1
        columns = list(table["displaycolumns"])
        if columns == ["#all"]:
            columns = list(table["columns"])
        if not 0 <= index < len(columns):
            return None
        return str(columns[index])

    def _move_display_column(
        self,
        table: ttk.Treeview,
        source: str,
        target: str,
    ) -> None:
        columns = list(table["displaycolumns"])
        if columns == ["#all"]:
            columns = list(table["columns"])
        if source not in columns or target not in columns:
            return

        columns.remove(source)
        target_index = columns.index(target)
        columns.insert(target_index, source)
        table["displaycolumns"] = columns

    def _active_sort_value(self, process: ProcessInfo, column: str) -> object:
        if column == "pid":
            return process.pid
        if column == "usage":
            return self.cpu_usage.get(str(process.pid), -1.0)
        if column == "path":
            return process.path.lower()
        return process.name.lower()

    def _limited_sort_value(self, row: dict[str, object], column: str) -> object:
        if column == "pid":
            value = row["pid"]
            return -1 if value == "" else int(value)
        if column in {"limit", "usage"}:
            value = row[column]
            return -1.0 if value == "--" else float(value)
        return str(row[column]).lower()

    def _update_cpu_usage(self, item_id: str, pid: int) -> None:
        try:
            current_cpu_time = get_process_cpu_time(pid)
        except Win32Error:
            self.cpu_usage.pop(item_id, None)
            return

        current_time = time.monotonic()
        previous = self.cpu_samples.get(item_id)
        self.cpu_samples[item_id] = (current_time, current_cpu_time)
        if previous is None:
            self.cpu_usage[item_id] = 0.0
            return

        previous_time, previous_cpu_time = previous
        self.cpu_usage[item_id] = calculate_cpu_percent(
            previous_time,
            previous_cpu_time,
            current_time,
            current_cpu_time,
        )

    def _update_active_cpu_usage(self) -> None:
        active_ids = set(self.active_processes)
        for item_id in active_ids:
            process = self.active_processes[item_id]
            self._update_cpu_usage(item_id, process.pid)

        tracked_ids = active_ids | set(self.sessions)
        for item_id in list(self.cpu_samples):
            if item_id not in tracked_ids:
                self.cpu_samples.pop(item_id, None)
                self.cpu_usage.pop(item_id, None)

    def _selected_active_ids(self) -> list[str]:
        return [item_id for item_id in self.active_table.selection() if item_id in self.active_processes]

    def _selected_limited_ids(self) -> list[str]:
        return [
            item_id
            for item_id in self.limited_table.selection()
            if item_id in self.sessions or self._is_config_row_id(item_id)
        ]

    def _parse_default_cpu(self) -> float | None:
        try:
            cpu_percent = parse_cpu_percent(self.cpu_var.get().strip())
        except ValueError as exc:
            messagebox.showerror("无效 CPU 限制", str(exc), parent=self)
            return None
        self._set_default_cpu(cpu_percent)
        return cpu_percent

    def _save_default_cpu(self) -> None:
        try:
            cpu_percent = parse_cpu_percent(self.cpu_var.get().strip())
        except ValueError:
            return
        self._set_default_cpu(cpu_percent)

    def _set_default_cpu(self, cpu_percent: float) -> None:
        self.config.default_cpu_percent = cpu_percent
        self._save_config()

    def _add_button_text(self) -> str:
        value = self.cpu_var.get().strip() or f"{SETTINGS.default_cpu_percent:g}"
        return f"> 限制 {value}%"

    def _refresh_add_button_text(self) -> None:
        self.add_button.configure(text=self._add_button_text())

    def _ask_cpu_percent(self, initial: float | None = None) -> float | None:
        initial_value = self.config.default_cpu_percent if initial is None else initial
        value = simpledialog.askstring(
            "设置 CPU 百分比",
            "CPU 硬限制 (%)",
            initialvalue=f"{initial_value:g}",
            parent=self,
        )
        if value is None:
            return None
        try:
            return parse_cpu_percent(value.strip())
        except ValueError as exc:
            messagebox.showerror("无效 CPU 限制", str(exc), parent=self)
            return None

    def _limit_selected_with_default(self) -> None:
        cpu_percent = self._parse_default_cpu()
        if cpu_percent is None:
            return
        self._limit_selected_active(cpu_percent)

    def _limit_selected_with_prompt(self) -> None:
        cpu_percent = self._ask_cpu_percent(self.config.default_cpu_percent)
        if cpu_percent is None:
            return
        self._limit_selected_active(cpu_percent)

    def _limit_selected_active(self, cpu_percent: float) -> None:
        item_ids = self._selected_active_ids()
        if not item_ids:
            self.status_var.set("未选择活动进程。")
            return

        added = 0
        errors: list[str] = []
        for item_id in item_ids:
            process = self.active_processes.get(item_id)
            if not process:
                continue
            try:
                session = limit_existing_process(process.pid, cpu_percent)
            except Win32Error as exc:
                errors.append(f"{process.pid} {process.name}: {exc}")
                continue

            self.sessions[item_id] = session
            self.limited_sources[item_id] = process
            self._save_process_limit(process, cpu_percent)
            self.active_processes.pop(item_id, None)
            added += 1

        self._render_active()
        self._render_limited()
        if added:
            self.status_var.set(f"已添加 {added} 个进程，CPU 限制 {cpu_percent:g}%。")
        if errors:
            messagebox.showerror("添加限制失败", "\n".join(errors[:8]), parent=self)

    def _release_selected_limited(self) -> None:
        item_ids = self._selected_limited_ids()
        if not item_ids:
            self.status_var.set("未选择受限进程。")
            return

        released = 0
        for item_id in item_ids:
            if self._is_config_row_id(item_id):
                key = self._config_key_from_row_id(item_id)
                if key in self.config.process_limits:
                    self.config.process_limits.pop(key, None)
                    self.auto_limit_failures.discard(key)
                    released += 1
                continue

            session = self.sessions.pop(item_id, None)
            if not session:
                continue
            session.close()
            self.cpu_samples.pop(item_id, None)
            self.cpu_usage.pop(item_id, None)
            process = self.limited_sources.pop(item_id, None)
            if process:
                self._remove_process_limit(process)
                self.active_processes[item_id] = process
            released += 1

        self._save_config()
        self._render_active()
        self._render_limited()
        self.status_var.set(f"已解除 {released} 个进程的限制。")

    def _set_limited_cpu_with_prompt(self) -> None:
        item_ids = self._selected_limited_ids()
        if not item_ids:
            self.status_var.set("未选择受限进程。")
            return

        first_cpu_percent = self._limited_item_cpu_percent(item_ids[0])
        cpu_percent = self._ask_cpu_percent(first_cpu_percent)
        if cpu_percent is None:
            return

        updated = 0
        errors: list[str] = []
        for item_id in item_ids:
            if self._is_config_row_id(item_id):
                key = self._config_key_from_row_id(item_id)
                if key in self.config.process_limits:
                    self.config.process_limits[key] = cpu_percent
                    self.auto_limit_failures.discard(key)
                    updated += 1
                continue

            session = self.sessions.get(item_id)
            if not session:
                continue
            try:
                session.set_cpu_percent(cpu_percent)
            except Win32Error as exc:
                errors.append(f"{session.pid}: {exc}")
                continue
            process = self.limited_sources.get(item_id)
            if process:
                self._save_process_limit(process, cpu_percent)
            updated += 1

        self._save_config()
        self._render_limited()
        if updated:
            self.status_var.set(f"已更新 {updated} 个进程，CPU 限制 {cpu_percent:g}%。")
        if errors:
            messagebox.showerror("设置限制失败", "\n".join(errors[:8]), parent=self)

    def _show_active_menu(self, event: tk.Event) -> None:
        self._select_row_under_pointer(self.active_table, event)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="添加默认限制", command=self._limit_selected_with_default)
        menu.add_command(label="设置 CPU 百分比并添加", command=self._limit_selected_with_prompt)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_limited_menu(self, event: tk.Event) -> None:
        self._select_row_under_pointer(self.limited_table, event)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="解除限制", command=self._release_selected_limited)
        menu.add_command(label="设置 CPU 百分比", command=self._set_limited_cpu_with_prompt)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _handle_active_double_click(self, event: tk.Event) -> None:
        region = self.active_table.identify_region(event.x, event.y)
        item_id = self.active_table.identify_row(event.y)
        if region not in {"cell", "tree"} or not item_id:
            return
        if item_id not in self.active_table.selection():
            self.active_table.selection_set(item_id)
            self.active_table.focus(item_id)
        self._limit_selected_with_default()

    def _select_row_under_pointer(self, table: ttk.Treeview, event: tk.Event) -> None:
        item_id = table.identify_row(event.y)
        if not item_id:
            return
        if item_id not in table.selection():
            table.selection_set(item_id)
            table.focus(item_id)

    def _process_key(self, process: ProcessInfo) -> str:
        return process_config_key(process.name, process.path)

    def _config_row_id(self, key: str) -> str:
        return f"config:{key}"

    def _is_config_row_id(self, item_id: str) -> bool:
        return item_id.startswith("config:")

    def _config_key_from_row_id(self, item_id: str) -> str:
        return item_id.removeprefix("config:")

    def _display_from_config_key(self, key: str) -> tuple[str, str]:
        if "\\" in key or "/" in key or ":" in key:
            return ntpath.basename(key) or key, key
        return key, ""

    def _limited_item_cpu_percent(self, item_id: str) -> float:
        if self._is_config_row_id(item_id):
            key = self._config_key_from_row_id(item_id)
            return self.config.process_limits.get(key, self.config.default_cpu_percent)

        session = self.sessions.get(item_id)
        if session:
            return session.cpu_percent
        return self.config.default_cpu_percent

    def _save_process_limit(self, process: ProcessInfo, cpu_percent: float) -> None:
        key = self._process_key(process)
        if not key:
            return
        self.config.process_limits[key] = cpu_percent
        self.auto_limit_failures.discard(key)
        self._save_config()

    def _remove_process_limit(self, process: ProcessInfo) -> None:
        key = self._process_key(process)
        if not key:
            return
        self.config.process_limits.pop(key, None)
        self.auto_limit_failures.discard(key)
        self._save_config()

    def _save_config(self) -> None:
        try:
            save_config(self.config)
        except OSError as exc:
            self.status_var.set(f"配置保存失败: {exc}")

    def _hide_to_tray(self) -> None:
        self._save_default_cpu()
        try:
            self.tray.start()
        except TrayUnavailable as exc:
            messagebox.showerror("托盘不可用", str(exc), parent=self)
            return
        self.withdraw()
        self.status_var.set("已托管到系统托盘，限制继续生效。")

    def _restore_from_tray(self) -> None:
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()
        self.status_var.set("已从系统托盘恢复。")

    def _exit_from_tray(self) -> None:
        self.exiting = True
        self.tray.stop()
        self.destroy()

    def destroy(self) -> None:
        self.tray.stop()
        for session in self.sessions.values():
            session.close()
        self.sessions.clear()
        super().destroy()


def main() -> int:
    app = CpuLimiterApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
