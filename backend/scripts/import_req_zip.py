"""Import Render Shell : ZIP du Registraire des entreprises (REQ).

Pourquoi ce script existe :
Le ZIP REQ « Données ouvertes » de donneesquebec.ca pèse ~225 Mo et
contient ~1 M de corporations. L'upload via le formulaire web échoue
sur Render Free :
- Le proxy/Cloudflare devant Render bloque les bodies >100 Mo
- Le timeout HTTP de 100 s coupe une ingestion de 2-5 minutes

Solution : depuis le Render Shell, on télécharge le ZIP depuis une URL
publique (le user le ré-upload temporairement sur transfer.sh, Google
Drive direct download, ou un bucket S3 public), puis on l'ingère
directement dans la DB. Pas de timeout HTTP, pas de body size limit.

Usage Render Shell :

    cd ~/project/src/backend

    # Variante 1 : depuis une URL (transfer.sh, GDrive, S3 public)
    python -m scripts.import_req_zip --url "https://transfer.sh/abc/JeuDonnees.zip"

    # Variante 2 : si tu as déjà uploadé le ZIP sur le filesystem
    # (peu probable sur Render Free, mais possible avec scp pour
    # un setup payant)
    python -m scripts.import_req_zip --zip /tmp/JeuDonnees.zip

    # Variante 3 : tester avec une limite
    python -m scripts.import_req_zip --url "..." --max-rows 5000

Conseils pour héberger le ZIP temporairement :
- transfer.sh   : `curl --upload-file JeuDonnees.zip https://transfer.sh/`
                  Retourne une URL valide ~14 jours.
- file.io       : upload web, lien expire après 1 download (à éviter
                  car le retry échoue).
- Google Drive  : partager → « Toute personne avec le lien », puis
                  utiliser https://drive.google.com/uc?export=download&id=FILE_ID

Mémoire : on charge le ZIP entier en RAM (225 Mo). Render Free a
512 Mo, donc OK avec un peu de marge. Si jamais OOM, on pourrait
streamer mais l'API actuelle d'`ingest_zip` attend un blob bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.integrations.req.companies import ingest_zip  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("import_req")


async def _download(url: str) -> bytes:
    """Télécharge le ZIP depuis l'URL fournie. Affiche la progression
    par 25 Mo pour qu'on voie que ça avance."""
    log.info("Téléchargement depuis %s…", url)
    started = time.monotonic()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(600.0, connect=30.0),
        follow_redirects=True,
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            chunks: list[bytes] = []
            received = 0
            next_log = 25 * 1024 * 1024
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                chunks.append(chunk)
                received += len(chunk)
                if received >= next_log:
                    pct = (
                        f" ({100 * received // total} %)"
                        if total
                        else ""
                    )
                    log.info(
                        "  %d Mo reçus%s",
                        received // 1024 // 1024,
                        pct,
                    )
                    next_log += 25 * 1024 * 1024
    elapsed = time.monotonic() - started
    blob = b"".join(chunks)
    log.info(
        "  ✓ %d Mo téléchargés en %.1f s",
        len(blob) // 1024 // 1024,
        elapsed,
    )
    return blob


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--url",
        help="URL publique du ZIP REQ (transfer.sh, Google Drive direct, S3).",
    )
    src.add_argument(
        "--zip",
        dest="zip_path",
        help="Chemin local du ZIP déjà présent sur le serveur.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        help="Limiter à N lignes (utile pour tester le pipeline).",
    )
    args = parser.parse_args()

    log.info("Ingestion du Registraire des entreprises (REQ) — démarrage…")

    if args.url:
        blob = await _download(args.url)
    else:
        log.info("Lecture du ZIP local %s…", args.zip_path)
        with open(args.zip_path, "rb") as fh:
            blob = fh.read()
        log.info("  ✓ %d Mo lus", len(blob) // 1024 // 1024)

    if args.max_rows:
        log.info("Limite : %d corporations", args.max_rows)
    else:
        log.info("Limite : aucune (~1 M corporations attendues)")

    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        try:
            result = await ingest_zip(
                db, blob, max_rows=args.max_rows
            )
            await db.commit()
        except Exception as exc:
            log.exception("Échec ingestion : %s", exc)
            return 1
    elapsed = time.monotonic() - started

    log.info(
        "✓ Terminé en %.1f s : %d lignes traitées, %d insérées/mises à jour.",
        elapsed,
        result.get("rows_processed", 0),
        result.get("rows_upserted", 0),
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
