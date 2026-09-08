from __future__ import annotations

import asyncio
import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import config
from scraper import Scraper, _load_urls


class RiftGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Rift Scanner")
        self.root.geometry("820x650")
        self.root.minsize(720, 560)

        self.event_queue: queue.Queue = queue.Queue()

        self.scan_thread: threading.Thread | None = None
        self.async_loop: asyncio.AbstractEventLoop | None = None
        self.scan_task: asyncio.Task | None = None

        self.stop_event = threading.Event()

        self.running = False
        self.closing = False
        self.scan_had_error = False
        self.scan_was_cancelled = False

        self.input_var = tk.StringVar(
            value=config.CONFIG.input_file
        )

        self.output_var = tk.StringVar(
            value=config.CONFIG.output_file
        )

        self.diagnostic_var = tk.StringVar(
            value=config.CONFIG.connect_diagnostic_file
        )

        dns_servers = list(config.CONFIG.dns_servers)

        self.dns1_var = tk.StringVar(
            value=dns_servers[0] if len(dns_servers) > 0 else ""
        )

        self.dns2_var = tk.StringVar(
            value=dns_servers[1] if len(dns_servers) > 1 else ""
        )

        self.concurrency_var = tk.StringVar(
            value=str(config.CONFIG.concurrency)
        )

        self.dns_timeout_var = tk.StringVar(
            value=str(config.CONFIG.dns_timeout)
        )

        self.total_timeout_var = tk.StringVar(
            value=str(config.CONFIG.total_timeout)
        )

        self.connect_timeout_var = tk.StringVar(
            value=str(config.CONFIG.connect_timeout)
        )

        self.sock_connect_timeout_var = tk.StringVar(
            value=str(config.CONFIG.sock_connect_timeout)
        )

        self.status_var = tk.StringVar(
            value="Ready"
        )

        self.input_count_var = tk.StringVar(value="0")
        self.processed_var = tk.StringVar(value="0")
        self.live_var = tk.StringVar(value="0")
        self.title_success_var = tk.StringVar(value="0")
        self.dns_failed_var = tk.StringVar(value="0")
        self.connect_failed_var = tk.StringVar(value="0")
        self.http_failed_var = tk.StringVar(value="0")
        self.no_title_var = tk.StringVar(value="0")
        self.redirects_var = tk.StringVar(value="0")
        self.errors_var = tk.StringVar(value="0")
        self.rate_var = tk.StringVar(value="0.0/s")

        self._build_ui()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self._on_close,
        )

        self.root.after(
            100,
            self._poll_events,
        )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        main = ttk.Frame(
            self.root,
            padding=12,
        )

        main.pack(
            fill="both",
            expand=True,
        )

        files_frame = ttk.LabelFrame(
            main,
            text="Files",
            padding=10,
        )

        files_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        self._file_row(
            files_frame,
            0,
            "Input",
            self.input_var,
            self._browse_input,
        )

        self._file_row(
            files_frame,
            1,
            "Output",
            self.output_var,
            self._browse_output,
        )

        self._file_row(
            files_frame,
            2,
            "Diagnostics",
            self.diagnostic_var,
            self._browse_diagnostic,
        )

        settings = ttk.LabelFrame(
            main,
            text="Settings",
            padding=10,
        )

        settings.pack(
            fill="x",
            pady=(0, 10),
        )

        self._setting_row(
            settings,
            0,
            "DNS 1",
            self.dns1_var,
        )

        self._setting_row(
            settings,
            1,
            "DNS 2",
            self.dns2_var,
        )

        self._setting_row(
            settings,
            2,
            "Concurrency",
            self.concurrency_var,
        )

        self._setting_row(
            settings,
            3,
            "DNS Timeout",
            self.dns_timeout_var,
        )

        self._setting_row(
            settings,
            4,
            "Total Timeout",
            self.total_timeout_var,
        )

        self._setting_row(
            settings,
            5,
            "Connect Timeout",
            self.connect_timeout_var,
        )

        self._setting_row(
            settings,
            6,
            "Socket Connect",
            self.sock_connect_timeout_var,
        )

        controls = ttk.Frame(main)

        controls.pack(
            fill="x",
            pady=(0, 10),
        )

        self.start_button = ttk.Button(
            controls,
            text="START SCAN",
            command=self._start_scan,
        )

        self.start_button.pack(
            side="left",
        )

        self.stop_button = ttk.Button(
            controls,
            text="STOP",
            command=self._stop_scan,
            state="disabled",
        )

        self.stop_button.pack(
            side="left",
            padx=(8, 0),
        )

        status_frame = ttk.LabelFrame(
            main,
            text="Status",
            padding=10,
        )

        status_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        ttk.Label(
            status_frame,
            textvariable=self.status_var,
        ).pack(
            anchor="w",
        )

        stats_frame = ttk.LabelFrame(
            main,
            text="Statistics",
            padding=10,
        )

        stats_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        stats = [
            ("Input", self.input_count_var),
            ("Processed", self.processed_var),
            ("Live 2xx", self.live_var),
            ("Title Success", self.title_success_var),
            ("DNS Failed", self.dns_failed_var),
            ("Connect Failed", self.connect_failed_var),
            ("HTTP Failed", self.http_failed_var),
            ("No Title", self.no_title_var),
            ("Redirects", self.redirects_var),
            ("Errors", self.errors_var),
            ("Rate", self.rate_var),
        ]

        for index, (label, variable) in enumerate(stats):
            row = index // 4
            column = index % 4

            cell = ttk.Frame(stats_frame)

            cell.grid(
                row=row,
                column=column,
                sticky="w",
                padx=8,
                pady=4,
            )

            ttk.Label(
                cell,
                text=f"{label}:",
            ).pack(
                side="left",
            )

            ttk.Label(
                cell,
                textvariable=variable,
            ).pack(
                side="left",
                padx=(4, 0),
            )

        log_frame = ttk.LabelFrame(
            main,
            text="Log",
            padding=8,
        )

        log_frame.pack(
            fill="both",
            expand=True,
        )

        self.log_text = tk.Text(
            log_frame,
            height=12,
            wrap="word",
            state="disabled",
        )

        self.log_text.pack(
            side="left",
            fill="both",
            expand=True,
        )

        log_scroll = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )

        log_scroll.pack(
            side="right",
            fill="y",
        )

        self.log_text.configure(
            yscrollcommand=log_scroll.set
        )

    def _file_row(
        self,
        parent,
        row,
        label,
        variable,
        browse_command,
    ):
        ttk.Label(
            parent,
            text=f"{label}:",
            width=14,
        ).grid(
            row=row,
            column=0,
            sticky="w",
            pady=4,
        )

        entry = ttk.Entry(
            parent,
            textvariable=variable,
        )

        entry.grid(
            row=row,
            column=1,
            sticky="ew",
            pady=4,
        )

        button = ttk.Button(
            parent,
            text="Browse",
            command=browse_command,
        )

        button.grid(
            row=row,
            column=2,
            padx=(8, 0),
            pady=4,
        )

        parent.columnconfigure(
            1,
            weight=1,
        )

        setattr(
            self,
            f"{label.lower()}_entry",
            entry,
        )

        setattr(
            self,
            f"{label.lower()}_browse",
            button,
        )

    def _setting_row(
        self,
        parent,
        row,
        label,
        variable,
    ):
        ttk.Label(
            parent,
            text=f"{label}:",
            width=18,
        ).grid(
            row=row,
            column=0,
            sticky="w",
            pady=3,
        )

        entry = ttk.Entry(
            parent,
            textvariable=variable,
            width=18,
        )

        entry.grid(
            row=row,
            column=1,
            sticky="w",
            pady=3,
        )

        setattr(
            self,
            f"{label.lower().replace(' ', '_')}_entry",
            entry,
        )

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select input file",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )

        if path:
            self.input_var.set(path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Select output file",
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )

        if path:
            self.output_var.set(path)

    def _browse_diagnostic(self):
        path = filedialog.asksaveasfilename(
            title="Select diagnostic file",
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )

        if path:
            self.diagnostic_var.set(path)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _apply_settings(self):
        input_file = self.input_var.get().strip()
        output_file = self.output_var.get().strip()
        diagnostic_file = self.diagnostic_var.get().strip()

        dns1 = self.dns1_var.get().strip()
        dns2 = self.dns2_var.get().strip()

        if not input_file:
            raise ValueError(
                "Input file is required."
            )

        if not output_file:
            raise ValueError(
                "Output file is required."
            )

        if not diagnostic_file:
            raise ValueError(
                "Diagnostic file is required."
            )

        dns_servers = [
            value
            for value in (dns1, dns2)
            if value
        ]

        if not dns_servers:
            raise ValueError(
                "At least one DNS server is required."
            )

        concurrency = int(
            self.concurrency_var.get().strip()
        )

        dns_timeout = float(
            self.dns_timeout_var.get().strip()
        )

        total_timeout = float(
            self.total_timeout_var.get().strip()
        )

        connect_timeout = float(
            self.connect_timeout_var.get().strip()
        )

        sock_connect_timeout = float(
            self.sock_connect_timeout_var.get().strip()
        )

        if concurrency < 1:
            raise ValueError(
                "Concurrency must be at least 1."
            )

        if dns_timeout <= 0:
            raise ValueError(
                "DNS timeout must be greater than 0."
            )

        if total_timeout <= 0:
            raise ValueError(
                "Total timeout must be greater than 0."
            )

        if connect_timeout <= 0:
            raise ValueError(
                "Connect timeout must be greater than 0."
            )

        if sock_connect_timeout <= 0:
            raise ValueError(
                "Socket connect timeout must be greater than 0."
            )

        config.CONFIG.input_file = input_file
        config.CONFIG.output_file = output_file
        config.CONFIG.connect_diagnostic_file = diagnostic_file

        # IMPORTANT:
        # scraper.py expects diagnostic_dir to be a Path.
        config.CONFIG.diagnostic_dir = Path(
            diagnostic_file
        ).parent

        config.CONFIG.dns_servers = dns_servers
        config.CONFIG.concurrency = concurrency
        config.CONFIG.dns_timeout = dns_timeout
        config.CONFIG.total_timeout = total_timeout
        config.CONFIG.connect_timeout = connect_timeout
        config.CONFIG.sock_connect_timeout = sock_connect_timeout

    # ------------------------------------------------------------------
    # Scan control
    # ------------------------------------------------------------------

    def _start_scan(self):
        if self.running:
            return

        try:
            self._apply_settings()

            urls = _load_urls(
                config.CONFIG.input_file
            )

            if not urls:
                messagebox.showwarning(
                    "No URLs",
                    "The input file contains no URLs.",
                    parent=self.root,
                )
                return

        except Exception as exc:
            messagebox.showerror(
                "Invalid settings",
                f"{type(exc).__name__}: {exc}",
                parent=self.root,
            )
            return

        self._reset_stats()
        self._clear_log()

        self.stop_event.clear()
        self.scan_had_error = False
        self.scan_was_cancelled = False
        self.closing = False
        self.running = True

        self.start_button.configure(
            state="disabled"
        )

        self.stop_button.configure(
            state="normal"
        )

        self._set_settings_state(
            "disabled"
        )

        self.status_var.set(
            f"Starting scan: {len(urls):,} URLs..."
        )

        self._log(
            f"Starting scan with {len(urls):,} URLs."
        )

        self.scan_thread = threading.Thread(
            target=self._run_scan_thread,
            args=(urls,),
            name="RiftScanThread",
            daemon=True,
        )

        self.scan_thread.start()

    def _run_scan_thread(self, urls):
        loop = asyncio.new_event_loop()

        self.async_loop = loop
        self.scan_task = None

        try:
            asyncio.set_event_loop(loop)

            self.event_queue.put(
                (
                    "log",
                    "Worker thread started.",
                )
            )

            task = loop.create_task(
                self._async_scan(urls)
            )

            self.scan_task = task

            self.event_queue.put(
                (
                    "log",
                    "Async task created.",
                )
            )

            if self.stop_event.is_set():
                task.cancel()

            loop.run_until_complete(task)

            self.event_queue.put(
                (
                    "log",
                    "Worker task completed normally.",
                )
            )

        except asyncio.CancelledError:
            self.scan_was_cancelled = True

            self.event_queue.put(
                (
                    "log",
                    "Worker task cancelled.",
                )
            )

        except Exception as exc:
            self.scan_had_error = True

            self.event_queue.put(
                (
                    "error",
                    f"{type(exc).__name__}: {exc}",
                )
            )

            self.event_queue.put(
                (
                    "traceback",
                    traceback.format_exc(),
                )
            )

        finally:
            self.scan_task = None

            try:
                loop.run_until_complete(
                    loop.shutdown_asyncgens()
                )
            except Exception:
                pass

            try:
                loop.run_until_complete(
                    loop.shutdown_default_executor()
                )
            except Exception:
                pass

            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass

            try:
                loop.close()
            except Exception:
                pass

            self.async_loop = None

            self.event_queue.put(
                (
                    "finished",
                    {
                        "error": self.scan_had_error,
                        "cancelled": self.scan_was_cancelled,
                    },
                )
            )

    async def _async_scan(self, urls):
        scraper = None

        def progress_callback(stats):
            self.event_queue.put(
                (
                    "stats",
                    dict(stats),
                )
            )

        self.event_queue.put(
            (
                "log",
                "Creating crawler...",
            )
        )

        try:
            scraper = Scraper(
                progress_callback=progress_callback,
            )

            self.event_queue.put(
                (
                    "log",
                    "Crawler created successfully.",
                )
            )

            # IMPORTANT:
            # BatchWriter expects Path objects, not strings.
            scraper.output_writer.path = Path(
                config.CONFIG.output_file
            )

            scraper.diagnostic_writer.path = Path(
                config.CONFIG.connect_diagnostic_file
            )

            self.event_queue.put(
                (
                    "log",
                    "Output path: "
                    f"{config.CONFIG.output_file}",
                )
            )

            self.event_queue.put(
                (
                    "log",
                    "Diagnostic path: "
                    f"{config.CONFIG.connect_diagnostic_file}",
                )
            )

            self.event_queue.put(
                (
                    "log",
                    "Initializing crawler...",
                )
            )

            await scraper.run(urls)

            self.event_queue.put(
                (
                    "log",
                    "Crawler run returned normally.",
                )
            )

        except asyncio.CancelledError:
            self.event_queue.put(
                (
                    "log",
                    "Crawler cancellation received.",
                )
            )
            raise

        except Exception as exc:
            self.event_queue.put(
                (
                    "error",
                    (
                        "Crawler failure: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            )

            self.event_queue.put(
                (
                    "traceback",
                    traceback.format_exc(),
                )
            )

            raise

        finally:
            if scraper is not None:
                try:
                    self.event_queue.put(
                        (
                            "stats",
                            dict(scraper.stats),
                        )
                    )
                except Exception:
                    pass

    def _stop_scan(self):
        if not self.running:
            return

        self.stop_event.set()
        self.scan_was_cancelled = True

        self.status_var.set(
            "Stopping..."
        )

        self.stop_button.configure(
            state="disabled"
        )

        self._log(
            "Stop requested. Cancelling active scan..."
        )

        loop = self.async_loop
        task = self.scan_task

        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(
                    task.cancel
                )

                self._log(
                    "Cancellation sent to worker."
                )

            except RuntimeError as exc:
                self._log(
                    f"Could not cancel worker: {exc}"
                )
        else:
            self._log(
                "Worker is still starting; stop will be "
                "handled as soon as the worker starts."
            )

    # ------------------------------------------------------------------
    # Events / statistics
    # ------------------------------------------------------------------

    def _poll_events(self):
        try:
            while True:
                event, data = (
                    self.event_queue.get_nowait()
                )

                if event == "stats":
                    self._update_stats(data)

                elif event == "log":
                    self._log(
                        str(data)
                    )

                elif event == "error":
                    self.scan_had_error = True

                    error_text = str(data)

                    self._log(
                        f"ERROR: {error_text}"
                    )

                    self.status_var.set(
                        "Error"
                    )

                    try:
                        messagebox.showerror(
                            "Rift Scan Error",
                            error_text,
                            parent=self.root,
                        )
                    except tk.TclError:
                        pass

                elif event == "traceback":
                    self.scan_had_error = True

                    self._log(
                        "----- TRACEBACK -----"
                    )

                    self._log(
                        str(data)
                    )

                    self._log(
                        "---------------------"
                    )

                elif event == "finished":
                    self._scan_finished(data)

        except queue.Empty:
            pass

        if not self.closing:
            self.root.after(
                100,
                self._poll_events,
            )

    def _update_stats(self, stats):
        self.input_count_var.set(
            f"{stats.get('input', 0):,}"
        )

        self.processed_var.set(
            f"{stats.get('processed', 0):,}"
        )

        self.live_var.set(
            f"{stats.get('live', 0):,}"
        )

        self.title_success_var.set(
            f"{stats.get('title_success', 0):,}"
        )

        self.dns_failed_var.set(
            f"{stats.get('dns_failed', 0):,}"
        )

        self.connect_failed_var.set(
            f"{stats.get('connect_failed', 0):,}"
        )

        self.http_failed_var.set(
            f"{stats.get('http_failed', 0):,}"
        )

        self.no_title_var.set(
            f"{stats.get('no_title', 0):,}"
        )

        self.redirects_var.set(
            f"{stats.get('redirects', 0):,}"
        )

        self.errors_var.set(
            f"{stats.get('errors', 0):,}"
        )

        processed = stats.get(
            "processed",
            0,
        )

        elapsed = stats.get(
            "elapsed",
            0.0,
        )

        if elapsed > 0:
            rate = processed / elapsed
        else:
            rate = 0.0

        self.rate_var.set(
            f"{rate:,.1f}/s"
        )

    def _scan_finished(self, result=None):
        if not self.running:
            return

        self.running = False

        self.start_button.configure(
            state="normal"
        )

        self.stop_button.configure(
            state="disabled"
        )

        self._set_settings_state(
            "normal"
        )

        had_error = self.scan_had_error

        if isinstance(result, dict):
            had_error = (
                had_error
                or bool(result.get("error"))
            )

        cancelled = (
            self.stop_event.is_set()
            or self.scan_was_cancelled
        )

        if had_error:
            self.status_var.set(
                "Error"
            )

            self._log(
                "Scan terminated because of an error."
            )

        elif cancelled:
            self.status_var.set(
                "Stopped"
            )

            self._log(
                "Scan stopped."
            )

        else:
            self.status_var.set(
                "Complete"
            )

            self._log(
                "Scan complete."
            )

        self.scan_thread = None
        self.async_loop = None
        self.scan_task = None

        if self.closing:
            self.root.after(
                50,
                self._finish_close,
            )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, message):
        try:
            self.log_text.configure(
                state="normal"
            )

            self.log_text.insert(
                "end",
                message.rstrip() + "\n",
            )

            self.log_text.see(
                "end"
            )

            self.log_text.configure(
                state="disabled"
            )

        except tk.TclError:
            pass

    def _clear_log(self):
        self.log_text.configure(
            state="normal"
        )

        self.log_text.delete(
            "1.0",
            "end",
        )

        self.log_text.configure(
            state="disabled"
        )

    # ------------------------------------------------------------------
    # Statistics reset
    # ------------------------------------------------------------------

    def _reset_stats(self):
        self.input_count_var.set("0")
        self.processed_var.set("0")
        self.live_var.set("0")
        self.title_success_var.set("0")
        self.dns_failed_var.set("0")
        self.connect_failed_var.set("0")
        self.http_failed_var.set("0")
        self.no_title_var.set("0")
        self.redirects_var.set("0")
        self.errors_var.set("0")
        self.rate_var.set("0.0/s")

    # ------------------------------------------------------------------
    # Widget state
    # ------------------------------------------------------------------

    def _set_settings_state(self, state):
        widgets = [
            self.input_entry,
            self.input_browse,
            self.output_entry,
            self.output_browse,
            self.diagnostics_entry,
            self.diagnostics_browse,
            self.dns_1_entry,
            self.dns_2_entry,
            self.concurrency_entry,
            self.dns_timeout_entry,
            self.total_timeout_entry,
            self.connect_timeout_entry,
            self.socket_connect_entry,
        ]

        for widget in widgets:
            widget.configure(
                state=state
            )

    # ------------------------------------------------------------------
    # Window closing
    # ------------------------------------------------------------------

    def _on_close(self):
        if not self.running:
            self.root.destroy()
            return

        answer = messagebox.askyesno(
            "Stop scan?",
            "A scan is currently running.\n\n"
            "Stop the scan and close Rift?",
            parent=self.root,
        )

        if not answer:
            return

        self.closing = True
        self.stop_event.set()
        self.scan_was_cancelled = True

        self.status_var.set(
            "Stopping..."
        )

        self.stop_button.configure(
            state="disabled"
        )

        self._log(
            "Closing requested. Cancelling scan..."
        )

        loop = self.async_loop
        task = self.scan_task

        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(
                    task.cancel
                )

                self._log(
                    "Cancellation sent to worker."
                )

            except RuntimeError:
                pass

        self.root.after(
            50,
            self._wait_for_scan_close,
        )

    def _wait_for_scan_close(self):
        if (
            self.scan_thread is not None
            and self.scan_thread.is_alive()
        ):
            self.root.after(
                50,
                self._wait_for_scan_close,
            )
            return

        self._finish_close()

    def _finish_close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    root = tk.Tk()

    RiftGUI(root)

    root.mainloop()


if __name__ == "__main__":
    main()