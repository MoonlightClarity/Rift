from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cleaner import clean_zone_file


class CleanerGUI(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title(
            "Rift - Zone Cleaner"
        )

        self.geometry(
            "700x420"
        )

        self.minsize(
            620,
            360,
        )

        self.input_var = tk.StringVar()

        self.output_var = tk.StringVar()

        self.status_var = tk.StringVar(
            value="Ready"
        )

        self.records_var = tk.StringVar(
            value="0"
        )

        self.hostnames_var = tk.StringVar(
            value="0"
        )

        self.duplicates_var = tk.StringVar(
            value="0"
        )

        self.rejected_var = tk.StringVar(
            value="0"
        )

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):

        root = ttk.Frame(
            self,
            padding=14,
        )

        root.pack(
            fill="both",
            expand=True,
        )

        ttk.Label(
            root,
            text="Rift Zone Cleaner",
            font=(
                "TkDefaultFont",
                16,
                "bold",
            ),
        ).pack(
            anchor="w",
            pady=(0, 12),
        )

        # --------------------------------------------------------------
        # Input
        # --------------------------------------------------------------

        input_frame = ttk.LabelFrame(
            root,
            text="Zone file",
            padding=10,
        )

        input_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        input_frame.columnconfigure(
            0,
            weight=1,
        )

        self.input_entry = ttk.Entry(
            input_frame,
            textvariable=self.input_var,
        )

        self.input_entry.grid(
            row=0,
            column=0,
            sticky="ew",
        )

        self.input_button = ttk.Button(
            input_frame,
            text="Browse",
            command=self._browse_input,
        )

        self.input_button.grid(
            row=0,
            column=1,
            padx=(8, 0),
        )

        # --------------------------------------------------------------
        # Output
        # --------------------------------------------------------------

        output_frame = ttk.LabelFrame(
            root,
            text="Clean URL output",
            padding=10,
        )

        output_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        output_frame.columnconfigure(
            0,
            weight=1,
        )

        self.output_entry = ttk.Entry(
            output_frame,
            textvariable=self.output_var,
        )

        self.output_entry.grid(
            row=0,
            column=0,
            sticky="ew",
        )

        self.output_button = ttk.Button(
            output_frame,
            text="Browse",
            command=self._browse_output,
        )

        self.output_button.grid(
            row=0,
            column=1,
            padx=(8, 0),
        )

        # --------------------------------------------------------------
        # Explanation
        # --------------------------------------------------------------

        explanation = ttk.Label(
            root,
            text=(
                "Extracts unique hostnames from the first field "
                "of each zone-file record and writes one HTTPS URL "
                "per line. DNS record types are ignored."
            ),
            wraplength=650,
        )

        explanation.pack(
            anchor="w",
            pady=(0, 12),
        )

        # --------------------------------------------------------------
        # Start
        # --------------------------------------------------------------

        controls = ttk.Frame(
            root
        )

        controls.pack(
            fill="x",
            pady=(0, 12),
        )

        self.start_button = ttk.Button(
            controls,
            text="CLEAN",
            command=self._start,
        )

        self.start_button.pack(
            side="left",
        )

        ttk.Label(
            controls,
            textvariable=self.status_var,
        ).pack(
            side="right",
        )

        # --------------------------------------------------------------
        # Statistics
        # --------------------------------------------------------------

        stats_frame = ttk.LabelFrame(
            root,
            text="Result",
            padding=10,
        )

        stats_frame.pack(
            fill="x",
            pady=(0, 10),
        )

        stats = [
            (
                "Records read",
                self.records_var,
            ),
            (
                "Unique hostnames",
                self.hostnames_var,
            ),
            (
                "Duplicates",
                self.duplicates_var,
            ),
            (
                "Rejected",
                self.rejected_var,
            ),
        ]

        for column, (
            label,
            variable,
        ) in enumerate(stats):

            stats_frame.columnconfigure(
                column,
                weight=1,
            )

            cell = ttk.Frame(
                stats_frame
            )

            cell.grid(
                row=0,
                column=column,
                sticky="w",
                padx=8,
            )

            ttk.Label(
                cell,
                text=label,
            ).pack(
                anchor="w"
            )

            ttk.Label(
                cell,
                textvariable=variable,
                font=(
                    "TkDefaultFont",
                    12,
                    "bold",
                ),
            ).pack(
                anchor="w"
            )

        # --------------------------------------------------------------
        # Log
        # --------------------------------------------------------------

        log_frame = ttk.LabelFrame(
            root,
            text="Log",
            padding=6,
        )

        log_frame.pack(
            fill="both",
            expand=True,
        )

        self.log = tk.Text(
            log_frame,
            height=8,
            wrap="word",
            state="disabled",
        )

        self.log.pack(
            fill="both",
            expand=True,
        )

    # ------------------------------------------------------------------
    # Browse
    # ------------------------------------------------------------------

    def _browse_input(self):

        path = filedialog.askopenfilename(
            title="Select zone file",
            filetypes=[
                (
                    "Zone/Text files",
                    "*.txt *.zone *.db",
                ),
                (
                    "All files",
                    "*.*",
                ),
            ],
        )

        if not path:
            return

        self.input_var.set(
            path
        )

        # Suggest an output filename based on the
        # selected input file, without hard-coding
        # a specific domain or filename.
        input_path = Path(
            path
        )

        suggested_output = (
            input_path.parent
            / f"{input_path.stem}_cleaned.txt"
        )

        self.output_var.set(
            str(
                suggested_output
            )
        )

    def _browse_output(self):

        path = filedialog.asksaveasfilename(
            title="Save cleaned URL file",
            defaultextension=".txt",
            filetypes=[
                (
                    "Text files",
                    "*.txt",
                ),
                (
                    "All files",
                    "*.*",
                ),
            ],
        )

        if path:
            self.output_var.set(
                path
            )

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def _start(self):

        if not self.input_var.get().strip():

            messagebox.showerror(
                "Missing input",
                "Select the zone file first.",
            )

            return

        if not self.output_var.get().strip():

            messagebox.showerror(
                "Missing output",
                "Select an output file first.",
            )

            return

        input_path = Path(
            self.input_var.get().strip()
        )

        if not input_path.is_file():

            messagebox.showerror(
                "File not found",
                f"Could not find:\n\n{input_path}",
            )

            return

        output_path = Path(
            self.output_var.get().strip()
        )

        if (
            output_path.resolve()
            == input_path.resolve()
        ):

            messagebox.showerror(
                "Invalid output",
                "The output file cannot be the same "
                "as the zone file.",
            )

            return

        # --------------------------------------------------------------
        # Confirm overwrite if necessary.
        # --------------------------------------------------------------

        if output_path.exists():

            answer = messagebox.askyesno(
                "Overwrite output?",
                (
                    f"{output_path}\n\n"
                    "already exists.\n\n"
                    "Replace it?"
                ),
            )

            if not answer:
                return

        self._reset()

        self.status_var.set(
            "Cleaning..."
        )

        self._set_controls(
            "disabled"
        )

        self._log(
            f"Input: {input_path}"
        )

        self._log(
            f"Output: {output_path}"
        )

        self._log(
            "Reading zone file..."
        )

        thread = threading.Thread(
            target=self._worker,
            args=(
                input_path,
                output_path,
            ),
            daemon=True,
        )

        thread.start()

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker(
        self,
        input_path: Path,
        output_path: Path,
    ):

        try:

            stats = clean_zone_file(
                input_path,
                output_path,
            )

            self.after(
                0,
                self._complete,
                stats,
            )

        except Exception as exc:

            self.after(
                0,
                self._error,
                exc,
            )

    # ------------------------------------------------------------------
    # Complete
    # ------------------------------------------------------------------

    def _complete(
        self,
        stats: dict[str, int],
    ):

        self.records_var.set(
            f"{stats['records_read']:,}"
        )

        self.hostnames_var.set(
            f"{stats['hostnames_found']:,}"
        )

        self.duplicates_var.set(
            f"{stats['duplicates']:,}"
        )

        self.rejected_var.set(
            f"{stats['rejected']:,}"
        )

        self._log(
            f"Records read: "
            f"{stats['records_read']:,}"
        )

        self._log(
            f"Unique hostnames: "
            f"{stats['hostnames_found']:,}"
        )

        self._log(
            f"Duplicates removed: "
            f"{stats['duplicates']:,}"
        )

        self._log(
            f"Rejected: "
            f"{stats['rejected']:,}"
        )

        self._log(
            f"URLs written: "
            f"{stats['output_count']:,}"
        )

        self._log(
            "Done."
        )

        self.status_var.set(
            "Complete"
        )

        self._set_controls(
            "normal"
        )

    # ------------------------------------------------------------------
    # Error
    # ------------------------------------------------------------------

    def _error(
        self,
        exc: Exception,
    ):

        self.status_var.set(
            "Error"
        )

        self._log(
            f"ERROR: "
            f"{type(exc).__name__}: {exc}"
        )

        self._set_controls(
            "normal"
        )

        messagebox.showerror(
            "Cleaner error",
            str(exc),
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def _reset(self):

        self.records_var.set(
            "0"
        )

        self.hostnames_var.set(
            "0"
        )

        self.duplicates_var.set(
            "0"
        )

        self.rejected_var.set(
            "0"
        )

        self.log.configure(
            state="normal"
        )

        self.log.delete(
            "1.0",
            "end",
        )

        self.log.configure(
            state="disabled"
        )

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def _set_controls(
        self,
        state: str,
    ):

        self.start_button.configure(
            state=state
        )

        self.input_button.configure(
            state=state
        )

        self.output_button.configure(
            state=state
        )

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _log(
        self,
        message: str,
    ):

        self.log.configure(
            state="normal"
        )

        self.log.insert(
            "end",
            message + "\n",
        )

        self.log.see(
            "end"
        )

        self.log.configure(
            state="disabled"
        )


if __name__ == "__main__":

    app = CleanerGUI()

    app.mainloop()