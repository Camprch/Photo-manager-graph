#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cœur de PhotoManager
- Logique de scan, redimension, compression, renommage
- Aucune dépendance à Tkinter / GUI
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Callable, Iterable, Optional, Dict, List

from PIL import Image, ImageOps, ExifTags

# Extensions supportées
SUPPORTED_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

ProgressCallback = Callable[[int, int], None]  # (processed, total)


@dataclass
class PhotoConfig:
    source_dir: Path
    dest_dir: Path
    max_width: int = 800
    max_height: int = 600
    quality: int = 70
    strip_metadata: bool = False
    recursive: bool = True

    # Renommage personnalisable
    # Variables disponibles:
    #   {folder}  -> nom du dossier source
    #   {date}    -> date au format YYYYMMDD
    #   {counter} -> compteur entier (par date)
    #   {orig}    -> nom de fichier original (sans extension)
    rename_pattern: str = "{folder}_{date}_{counter:03d}"

    # Format de sortie (géré par Pillow: "JPEG", "PNG", "WEBP", ...)
    output_format: str = "JPEG"


def exif_datetime(img: Image.Image, src: Path) -> datetime:
    """Essaie de récupérer la date EXIF, sinon mtime, sinon maintenant."""
    try:
        exif = img.getexif()
        if exif and len(exif) > 0:
            for k, v in exif.items():
                if ExifTags.TAGS.get(k, k) == 'DateTimeOriginal' and isinstance(v, str):
                    v2 = v.replace(':', '-', 2)
                    return datetime.fromisoformat(v2)
    except Exception:
        pass

    try:
        return datetime.fromtimestamp(src.stat().st_mtime)
    except Exception:
        return datetime.now()


def ensure_rgb(img: Image.Image) -> Image.Image:
    """Convertit en RGB si nécessaire (pour JPEG)."""
    if img.mode in ('RGBA', 'LA', 'P', 'CMYK'):
        return img.convert('RGB')
    return img


def _iter_images(folder: Path, recursive: bool) -> Iterable[Path]:
    exts = SUPPORTED_EXT
    if recursive:
        for p in folder.rglob('*'):
            if p.is_file() and p.suffix.lower() in exts:
                yield p
    else:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                yield p


def gather_images(config: PhotoConfig) -> List[Path]:
    """Retourne la liste des images à traiter."""
    return list(_iter_images(config.source_dir, config.recursive))


def _build_base_name(
    config: PhotoConfig,
    src: Path,
    parent_name: str,
    counters: Dict[str, int],
    dt: datetime,
) -> str:
    day_key = dt.strftime('%Y%m%d')
    counters.setdefault(day_key, 0)
    counters[day_key] += 1

    ctx = {
        "folder": parent_name,
        "date": day_key,
        "counter": counters[day_key],
        "orig": src.stem,
    }

    # On essaie le pattern de l'utilisateur, et on fallback sur l'ancien comportement si erreur
    try:
        base = config.rename_pattern.format(**ctx)
        if not base:
            raise ValueError("empty name")
        return base
    except Exception:
        return f"{parent_name}_{day_key}_{counters[day_key]:03d}"


def unique_path(folder: Path, base_name: str, ext: str) -> Path:
    """
    Génère un chemin unique:
    - d'abord <base_name><ext>
    - si déjà existant: <base_name>_001<ext>, _002, etc.
    """
    candidate = folder / f"{base_name}{ext}"
    if not candidate.exists():
        return candidate

    i = 1
    while True:
        candidate = folder / f"{base_name}_{i:03d}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def process_images(
    config: PhotoConfig,
    images: Optional[Iterable[Path]] = None,
    progress_cb: Optional[ProgressCallback] = None,
) -> int:
    """
    Traite les images selon la config.
    - images: liste/itérable d'images à traiter. Si None, on scanne selon la config.
    - progress_cb(processed, total): callback de progression (optionnel).
    Retourne le nombre d'images traitées.
    """
    src_dir = config.source_dir
    dst_dir = config.dest_dir

    dst_dir.mkdir(parents=True, exist_ok=True)

    if images is None:
        images_list = gather_images(config)
    else:
        images_list = list(images)

    total = len(images_list)
    if total == 0:
        return 0

    parent_name = src_dir.name
    counters: Dict[str, int] = {}
    processed = 0

    fmt = config.output_format.upper()
    if fmt == "JPEG":
        ext = ".jpg"
    else:
        ext = f".{fmt.lower()}"

    for src in images_list:
        try:
            im = Image.open(src)
            try:
                im = ImageOps.exif_transpose(im)
                dt = exif_datetime(im, src)

                base_name = _build_base_name(config, src, parent_name, counters, dt)

                # Resize
                im = ensure_rgb(im)
                im.thumbnail((config.max_width, config.max_height), Image.Resampling.LANCZOS)

                out_path = unique_path(dst_dir, base_name, ext)

                save_kwargs = dict(format=fmt, quality=config.quality, optimize=True)
                if fmt == "JPEG":
                    save_kwargs["subsampling"] = "4:2:0"

                if not config.strip_metadata:
                    exif = im.info.get('exif')
                    icc = im.info.get('icc_profile')
                    if exif:
                        save_kwargs['exif'] = exif
                    if icc:
                        save_kwargs['icc_profile'] = icc

                im.save(out_path, **save_kwargs)

            finally:
                im.close()
        except Exception as e:
            # On log sur stdout/stderr, mais on continue
            print(f"[ERREUR] {src}: {e}")

        processed += 1
        if progress_cb is not None:
            progress_cb(processed, total)

    return processed
