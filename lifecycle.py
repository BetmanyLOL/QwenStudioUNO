#!/usr/bin/env python3
"""
Nexus Hub — lifecycle.py

Corre dentro del GitHub Action (nexus-lifecycle.yml). Implementa el modelo
híbrido FIFO con aviso descrito en Qwen_Studio_Nexus_Arquitectura:

1. Cuenta los Nexos "ocupando cupo" (status active o at_risk).
2. Si ese total entra en la zona de aviso (>= warning_threshold), marca
   los más antiguos que todavía estén "active" como at_risk y les pone
   warned_at con la fecha actual (solo una vez; no los vuelve a tocar).
3. Si el total supera el límite duro (>= limit), borra los .html de los
   Nexos at_risk más antiguos (los que NO están saved/resubmitted) hasta
   volver dentro del cupo, y elimina su entrada del manifest por completo.

No depende de librerías externas: solo usa la librería estándar de Python,
porque el script opera sobre el checkout local del repo (no llama a la API
de GitHub), así que no hace falta PyGithub ni nada parecido.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.json"
NEXOS_DIR = REPO_ROOT / "nexos"

OCCUPYING_STATUSES = {"active", "at_risk"}
PROTECTED_STATUSES = {"saved", "resubmitted"}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_created_at(nexo):
    # Nexos sin fecha válida se tratan como los más antiguos (se procesan primero)
    try:
        return datetime.strptime(nexo["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, ValueError):
        return datetime.min


def load_manifest():
    if not MANIFEST_PATH.exists():
        print(f"::error::No se encontró {MANIFEST_PATH}")
        sys.exit(1)
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest):
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def mark_at_risk(manifest):
    """Paso 2: marca los Nexos activos más antiguos como at_risk si hace falta."""
    limit = manifest["limit"]
    warning_threshold = manifest["warning_threshold"]
    nexos = manifest["nexos"]

    occupying = [n for n in nexos if n["status"] in OCCUPYING_STATUSES]
    total = len(occupying)

    if total < warning_threshold:
        print(f"Total ocupando cupo: {total}/{limit} — fuera de la zona de aviso.")
        return

    needed = total - warning_threshold + 1
    candidates = sorted(
        (n for n in nexos if n["status"] == "active"),
        key=parse_created_at,
    )

    marked = 0
    for nexo in candidates:
        if marked >= needed:
            break
        nexo["status"] = "at_risk"
        nexo["warned_at"] = now_iso()
        marked += 1
        print(f"  → marcado at_risk: {nexo['id']} ({nexo.get('title', 'sin título')})")

    if marked:
        print(f"Se marcaron {marked} Nexo(s) como at_risk (total {total}/{limit}).")
    else:
        print("En zona de aviso pero no hay más Nexos 'active' para marcar.")


def delete_excess(manifest):
    """Paso 3: borra los .html más antiguos en at_risk hasta volver al límite."""
    limit = manifest["limit"]
    nexos = manifest["nexos"]

    deletable = [n for n in nexos if n["status"] == "at_risk"]
    deletable.sort(key=parse_created_at)

    occupying_count = len([n for n in nexos if n["status"] in OCCUPYING_STATUSES])
    if occupying_count <= limit:
        print(f"Total ocupando cupo: {occupying_count}/{limit} — dentro del límite, no hay borrado.")
        return

    to_delete = occupying_count - limit
    deleted_ids = []

    for nexo in deletable[:to_delete]:
        html_path = NEXOS_DIR / f"{nexo['id']}.html"
        if html_path.exists():
            html_path.unlink()
            print(f"  → borrado archivo: {html_path.name}")
        else:
            print(f"  → aviso: {html_path.name} no existía en disco")
        deleted_ids.append(nexo["id"])

    manifest["nexos"] = [n for n in nexos if n["id"] not in deleted_ids]

    if deleted_ids:
        print(f"Se eliminaron {len(deleted_ids)} Nexo(s) del manifest: {', '.join(deleted_ids)}")


def main():
    manifest = load_manifest()

    if "limit" not in manifest or "warning_threshold" not in manifest:
        print("::error::manifest.json debe tener 'limit' y 'warning_threshold'")
        sys.exit(1)

    mark_at_risk(manifest)
    delete_excess(manifest)

    save_manifest(manifest)
    print("manifest.json actualizado.")


if __name__ == "__main__":
    main()
