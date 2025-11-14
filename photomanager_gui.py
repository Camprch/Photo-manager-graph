#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PhotoManager GUI - Lightweight local app (Windows 11)

- Redimensionne dans une boîte WxH en conservant les proportions
- Compresse en JPG/PNG/WEBP (qualité ajustable pour formats avec qualité)
- Renommage configurable via pattern:
    {folder}  -> nom du dossier d'entrée
    {date}    -> YYYYMMDD
    {counter} -> compteur (entier) par date
    {orig}    -> nom de fichier original sans extension
- Sortie: dossier choisi (par défaut <input>/output)
- Option récursive (sous-dossiers)
- Support "glisser-déposer" du dossier via .bat (argv)
Dépendances: Pillow (PIL), Tkinter
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from photomanager_core import (
    PhotoConfig,
    gather_images,
    process_images,
    SUPPORTED_EXT,
)


class PhotoManagerGUI(tk.Tk):
    def __init__(self, preset_input: Path | None = None):
        super().__init__()
        self.title("PhotoManager GUI")
        self.geometry("700x430")
        self.resizable(False, False)

        # Variables de configuration
        self.input_dir = tk.StringVar(value=str(preset_input) if preset_input else "")
        self.output_dir = tk.StringVar(
            value=str((preset_input / "output").resolve()) if preset_input else ""
        )
        self.max_w = tk.IntVar(value=800)
        self.max_h = tk.IntVar(value=600)
        self.quality = tk.IntVar(value=70)
        self.strip_metadata = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=True)  # par défaut: récursif activé

        # Nouveaux paramètres
        self.rename_pattern = tk.StringVar(
            value="{folder}_{date}_{counter:03d}"
        )
        self.output_format = tk.StringVar(value="JPEG")

        self._build_ui()

        self.progress_max = 0

    def _build_ui(self):
        pad = {'padx': 10, 'pady': 6}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        # Input folder
        row1 = ttk.Frame(frm)
        row1.pack(fill="x", **pad)
        ttk.Label(row1, text="Dossier d'entrée:").pack(side="left")
        ttk.Entry(row1, textvariable=self.input_dir, width=55).pack(side="left", padx=6)
        ttk.Button(row1, text="Parcourir...", command=self.browse_input).pack(side="left")

        # Output folder
        row2 = ttk.Frame(frm)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="Dossier de sortie:").pack(side="left")
        ttk.Entry(row2, textvariable=self.output_dir, width=55).pack(side="left", padx=6)
        ttk.Button(row2, text="Parcourir...", command=self.browse_output).pack(side="left")

        # Options de base
        row3 = ttk.Frame(frm)
        row3.pack(fill="x", **pad)
        ttk.Label(row3, text="Largeur max:").pack(side="left")
        ttk.Entry(row3, textvariable=self.max_w, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(row3, text="Hauteur max:").pack(side="left")
        ttk.Entry(row3, textvariable=self.max_h, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(row3, text="Qualité (1-100):").pack(side="left")
        ttk.Entry(row3, textvariable=self.quality, width=6).pack(side="left", padx=(4, 12))

        # Format + strip + récursif
        row3b = ttk.Frame(frm)
        row3b.pack(fill="x", **pad)

        ttk.Label(row3b, text="Format de sortie:").pack(side="left")
        ttk.Combobox(
            row3b,
            textvariable=self.output_format,
            values=["JPEG", "PNG", "WEBP"],
            width=8,
            state="readonly",
        ).pack(side="left", padx=(4, 15))

        ttk.Checkbutton(
            row3b,
            text="Supprimer métadonnées (strip)",
            variable=self.strip_metadata
        ).pack(side="left", padx=(0, 15))

        ttk.Checkbutton(
            row3b,
            text="Traiter aussi les sous-dossiers (récursif)",
            variable=self.recursive
        ).pack(side="left")

        # Renommage
        row4 = ttk.LabelFrame(frm, text="Renommage")
        row4.pack(fill="x", **pad)

        sub4 = ttk.Frame(row4)
        sub4.pack(fill="x", pady=4, padx=4)
        ttk.Label(sub4, text="Pattern:").pack(side="left")
        ttk.Entry(
            sub4,
            textvariable=self.rename_pattern,
            width=60
        ).pack(side="left", padx=(6, 4))

        ttk.Label(
            row4,
            text="Variables: {folder}, {date}, {counter}, {orig}",
            foreground="gray"
        ).pack(anchor="w", padx=6, pady=(0, 4))

        # Progress
        row5 = ttk.Frame(frm)
        row5.pack(fill="x", **pad)
        self.pb = ttk.Progressbar(
            row5,
            orient="horizontal",
            mode="determinate",
            length=550,
            maximum=100
        )
        self.pb.pack(side="left", padx=(0, 10))
        self.lbl_progress = ttk.Label(row5, text="0 / 0")
        self.lbl_progress.pack(side="left")

        # Buttons
        row6 = ttk.Frame(frm)
        row6.pack(fill="x", **pad)
        ttk.Button(row6, text="Lancer le traitement", command=self.on_run).pack(side="left")
        ttk.Button(row6, text="Quitter", command=self.destroy).pack(side="right")

        # Footer
        ttk.Label(
            frm,
            text="PhotoManager GUI — Python + Pillow — Windows 11"
        ).pack(side="bottom", pady=8)

    def browse_input(self):
        path = filedialog.askdirectory(title="Choisir le dossier d'entrée")
        if path:
            self.input_dir.set(path)
            out = Path(path) / "output"
            self.output_dir.set(str(out))

    def browse_output(self):
        path = filedialog.askdirectory(title="Choisir le dossier de sortie")
        if path:
            self.output_dir.set(path)

    def _build_config(self) -> PhotoConfig | None:
        """Construit la PhotoConfig à partir des champs GUI, ou retourne None si erreur."""
        try:
            in_dir = Path(self.input_dir.get()).resolve()
            if not in_dir.exists() or not in_dir.is_dir():
                messagebox.showerror("Erreur", "Dossier d'entrée invalide.")
                return None

            if self.output_dir.get().strip():
                out_dir = Path(self.output_dir.get()).resolve()
            else:
                out_dir = (in_dir / "output").resolve()

            out_dir.mkdir(parents=True, exist_ok=True)

            try:
                w = int(self.max_w.get())
                h = int(self.max_h.get())
                q = int(self.quality.get())
            except Exception:
                messagebox.showerror(
                    "Erreur",
                    "Paramètres invalides (valeurs numériques requises)."
                )
                return None

            if w <= 0 or h <= 0 or not (1 <= q <= 100):
                messagebox.showerror(
                    "Erreur",
                    "Paramètres invalides (w/h > 0, qualité 1..100)."
                )
                return None

            cfg = PhotoConfig(
                source_dir=in_dir,
                dest_dir=out_dir,
                max_width=w,
                max_height=h,
                quality=q,
                strip_metadata=self.strip_metadata.get(),
                recursive=self.recursive.get(),
                rename_pattern=self.rename_pattern.get().strip()
                or "{folder}_{date}_{counter:03d}",
                output_format=self.output_format.get().strip() or "JPEG",
            )
            return cfg

        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            return None

    def _update_progress(self, processed: int, total: int):
        self.pb['maximum'] = total
        self.pb['value'] = processed
        self.lbl_progress.config(text=f"{processed} / {total}")

    def on_run(self):
        cfg = self._build_config()
        if cfg is None:
            return

        # Collecte des images (et affiche un message si 0 image)
        imgs = gather_images(cfg)
        if not imgs:
            messagebox.showinfo(
                "Info",
                "Aucune image trouvée dans le dossier (et sous-dossiers si activé).\n"
                f"Extensions supportées: {', '.join(sorted(SUPPORTED_EXT))}"
            )
            return

        self.progress_max = len(imgs)
        self.pb['value'] = 0
        self.pb['maximum'] = self.progress_max
        self.lbl_progress.config(text=f"0 / {self.progress_max}")

        # Thread de travail pour ne pas bloquer la GUI
        def worker():
            try:
                def progress_cb(done: int, total: int):
                    # On renvoie la mise à jour dans le thread Tk principal
                    self.after(0, lambda: self._update_progress(done, total))

                processed = process_images(cfg, images=imgs, progress_cb=progress_cb)

                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Terminé",
                        f"Traitement terminé !\n"
                        f"Images traitées : {processed}\n"
                        f"Sortie : {cfg.dest_dir}"
                    )
                )
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Erreur", str(e)))

        t = threading.Thread(target=worker, daemon=True)
        t.start()


def get_preset_from_argv():
    # Si on passe un dossier en argument (drag & drop sur le .bat), on le pré-remplit
    if len(sys.argv) >= 2:
        p = Path(sys.argv[1]).expanduser().resolve()
        if p.exists() and p.is_dir():
            return p
    return None


if __name__ == "__main__":
    preset = get_preset_from_argv()
    app = PhotoManagerGUI(preset_input=preset)
    app.mainloop()
