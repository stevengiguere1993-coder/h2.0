"""Import CLI : ZIP provincial XML du rôle d'évaluation foncière du Québec.

Pourquoi ce script existe :
Le ZIP « Tous les fichiers des rôles d'évaluation foncière » du MAMH
contient 1 134 fichiers XML (un par municipalité du Québec) et pèse
~520 Mo compressé. Décompressé en mémoire/disque ça dépasse facilement
les 5 Go.

Sur Render Free (512 Mo RAM, 100 s timeout HTTP, 1 Go disque éphémère),
l'import via le formulaire web finit toujours par crasher quelque part :
OOM sur un gros XML (Montréal ~150 Mo décompressé) ou worker tué par
le scheduler.

**La solution propre** : lancer ce script sur ton VPS Hetzner (qui a
plusieurs Go de RAM disponibles, pas de timeout, du disque), pointé
sur la DB Render via DATABASE_URL. Le script écrit directement dans
`mtl_property_units` — le portail interroge la même table.

Usage Hetzner (ou Render Shell payant) :

    # 1) Clone le repo côté serveur
    git clone https://github.com/stevengiguere1993-coder/h2.0.git
    cd h2.0/backend

    # 2) Installe les deps Python
    pip install -r requirements.txt

    # 3) Exporte la DATABASE_URL Render (Settings > Environment)
    export DATABASE_URL='postgresql://USER:PASS@HOST.render.com/DB'

    # 4a) Import du ZIP provincial complet depuis une URL
    python -m scripts.import_provincial_xml_zip \\
        --url 'https://www.donneesquebec.ca/...rolex.zip'

    # 4b) OU depuis un ZIP déjà téléchargé
    python -m scripts.import_provincial_xml_zip --zip /tmp/roles.zip

    # 4c) OU UN seul XML (typiquement Montréal RL66023, déjà sur Hetzner)
    python -m scripts.import_provincial_xml_zip \\
        --xml /data/RL66023_2026.xml

    # 4d) OU un dossier de XMLs déjà extraits
    python -m scripts.import_provincial_xml_zip --xml-dir /data/roles/

    # OU avec une limite pour tester
    python -m scripts.import_provincial_xml_zip --zip /tmp/roles.zip \\
        --max-rows 50000

Options utiles :
    --max-km 50         Filtre distance (défaut 50 km depuis MTL)
    --max-km 0          Désactive le filtre — importe TOUT le Québec
    --batch-size 5000   Taille de bulk insert (défaut 2000)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tempfile
from typing import Optional

import httpx


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def _download_to_tmp(url: str) -> str:
    """Télécharge l'URL dans un fichier temporaire, retourne le path."""
    log = logging.getLogger("download")
    fd, path = tempfile.mkstemp(suffix=".zip", prefix="provincial-")
    os.close(fd)

    log.info("Download %s → %s", url, path)
    total = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30.0)) as client:
        async with client.stream("GET", url, follow_redirects=True) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
                    total += len(chunk)
                    if total % (50 * 1024 * 1024) == 0:
                        log.info("  %d Mo téléchargés…", total // (1024 * 1024))
    log.info("Téléchargement terminé : %d Mo", total // (1024 * 1024))
    return path


async def _run(
    zip_path: str,
    *,
    region: str,
    max_rows: Optional[int],
    max_km: Optional[float],
    batch_size: int,
) -> None:
    """Import principal — utilise la même fonction que le worker web."""
    log = logging.getLogger("import")

    # Import ici pour pouvoir lire DATABASE_URL avant d'init SQLAlchemy.
    from app.db.session import AsyncSessionLocal
    from app.integrations.roles_evaluation.quebec_regional import (
        ingest_provincial_csv,
    )

    log.info(
        "Démarrage ingestion : zip=%s region=%s max_rows=%s max_km=%s batch=%d",
        zip_path,
        region,
        max_rows,
        max_km,
        batch_size,
    )

    async with AsyncSessionLocal() as session:
        result = await ingest_provincial_csv(
            session,
            zip_path,
            region=region,
            batch_size=batch_size,
            max_rows=max_rows,
            max_km_from_mtl=max_km,
        )
        await session.commit()

    log.info(
        "✅ Ingestion terminée : %d unités lues, %d sauvegardées (region=%s)",
        result.get("rows_processed", 0),
        result.get("rows_upserted", 0),
        result.get("region"),
    )

    diags = result.get("diagnostics") or []
    ok = [d for d in diags if not d.get("error") and d.get("encoding") not in ("skipped",)]
    skipped = [d for d in diags if d.get("encoding") == "skipped"]
    errored = [d for d in diags if d.get("error")]

    log.info(
        "Diagnostics : %d fichiers traités · %d ignorés (hors-périmètre) · %d erreurs",
        len(ok),
        len(skipped),
        len(errored),
    )
    if errored:
        log.warning("=== Fichiers en erreur ===")
        for d in errored[:20]:
            log.warning("  %s : %s", d.get("file"), d.get("error"))
    if ok:
        log.info("=== Premiers fichiers importés (sample) ===")
        for d in ok[:10]:
            headers = " · ".join(d.get("headers_seen") or [])
            log.info("  %s : %s", d.get("file"), headers)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Importe le ZIP provincial XML du rôle d'évaluation foncière "
            "du Québec dans la table mtl_property_units."
        )
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--zip", help="Path local vers un ZIP déjà téléchargé."
    )
    src.add_argument(
        "--url",
        help=(
            "URL publique du ZIP (donneesquebec.ca, transfer.sh…). "
            "Téléchargé en streaming dans /tmp avant ingest."
        ),
    )
    src.add_argument(
        "--xml",
        help=(
            "Path local vers UN fichier XML MAMH (ex. RL66023_2026.xml "
            "pour Montréal). Sera empaqueté dans un ZIP temporaire "
            "avant ingest. Utile sur Hetzner si Montréal est déjà "
            "sur disque."
        ),
    )
    src.add_argument(
        "--xml-dir",
        help=(
            "Path vers un dossier contenant plusieurs fichiers XML "
            "MAMH. Tous les .xml du dossier sont empaquetés dans un "
            "ZIP temporaire avant ingest."
        ),
    )
    parser.add_argument(
        "--region",
        default="quebec",
        choices=["quebec", "rive-sud", "laval", "rive-nord"],
        help="Étiquette region écrite dans chaque row.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Limite globale d'unités (utile pour tester). Default = aucun.",
    )
    parser.add_argument(
        "--max-km",
        type=float,
        default=50.0,
        help=(
            "Filtre distance depuis MTL (défaut 50 km). 0 ou -1 = "
            "désactive le filtre (importe TOUT le Québec)."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Bulk insert batch size (défaut 2000).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Debug logging."
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)
    log = logging.getLogger("main")

    if not os.environ.get("DATABASE_URL"):
        log.error(
            "DATABASE_URL n'est pas défini dans l'environnement. "
            "Exporte-le avant de lancer le script :\n"
            "  export DATABASE_URL='postgresql://USER:PASS@HOST.render.com/DB'"
        )
        return 2

    max_km: Optional[float] = (
        None if args.max_km <= 0 else float(args.max_km)
    )

    async def _go() -> None:
        import zipfile

        zip_path = args.zip
        downloaded_temp = False
        wrapped_temp = False

        if args.url:
            zip_path = await _download_to_tmp(args.url)
            downloaded_temp = True
        elif args.xml:
            # Empaquette le XML dans un ZIP temporaire pour réutiliser
            # le pipeline d'ingestion existant (qui attend un ZIP).
            xml_path = args.xml
            if not os.path.isfile(xml_path):
                log.error("XML introuvable : %s", xml_path)
                raise SystemExit(1)
            fd, zip_path = tempfile.mkstemp(
                suffix=".zip", prefix="provincial-single-"
            )
            os.close(fd)
            wrapped_temp = True
            log.info("Empaquette %s → %s", xml_path, zip_path)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                zf.write(xml_path, arcname=os.path.basename(xml_path))
        elif args.xml_dir:
            xml_dir = args.xml_dir
            if not os.path.isdir(xml_dir):
                log.error("Dossier introuvable : %s", xml_dir)
                raise SystemExit(1)
            xml_files = sorted(
                os.path.join(xml_dir, f)
                for f in os.listdir(xml_dir)
                if f.lower().endswith(".xml")
            )
            if not xml_files:
                log.error("Aucun .xml dans %s", xml_dir)
                raise SystemExit(1)
            fd, zip_path = tempfile.mkstemp(
                suffix=".zip", prefix="provincial-dir-"
            )
            os.close(fd)
            wrapped_temp = True
            log.info(
                "Empaquette %d XML de %s → %s",
                len(xml_files),
                xml_dir,
                zip_path,
            )
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                for xml_path in xml_files:
                    zf.write(xml_path, arcname=os.path.basename(xml_path))

        try:
            await _run(
                zip_path,
                region=args.region,
                max_rows=args.max_rows,
                max_km=max_km,
                batch_size=args.batch_size,
            )
        finally:
            if downloaded_temp or wrapped_temp:
                try:
                    os.unlink(zip_path)
                except OSError:
                    pass

    try:
        asyncio.run(_go())
    except KeyboardInterrupt:
        log.warning("Interrompu manuellement.")
        return 130
    except Exception as exc:  # noqa: BLE001
        log.exception("Échec : %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
