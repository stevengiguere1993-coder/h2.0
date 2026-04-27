"""Import Render Shell : Rôle d'évaluation foncière Montréal.

Pourquoi ce script existe :
L'endpoint HTTP POST /admin/data/mtl-roles/import télécharge un CSV
de 150-200 Mo et l'ingère par batches dans `mtl_property_units`.
Sur Render free tier, le timeout HTTP est de 100 s, ce qui est
insuffisant : le download seul prend ~30-60 s, le parsing + bulk
insert prennent encore 2-5 min. Résultat : « Internal Server Error ».

Solution : lancer l'ingestion depuis le Render Shell, qui n'a pas
de timeout HTTP. La fonction sous-jacente est la même
(`app.integrations.roles_evaluation.montreal.ingest_csv`).

Usage Render Shell :
    cd ~/project/src/backend
    python -m scripts.import_montreal_roles
    # ou avec un fichier CSV local déjà téléchargé :
    python -m scripts.import_montreal_roles --csv /tmp/roles.csv
    # ou pour tester avec une petite portion :
    python -m scripts.import_montreal_roles --max-rows 1000

Mémoire : pas un problème. Le streaming + batches de 2000 lignes
gardent la consommation autour de 50-100 Mo, bien sous le quota
de 512 Mo Render free.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.integrations.roles_evaluation.montreal import (  # noqa: E402
    MTL_CSV_URL,
    ingest_csv,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("import_mtl")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        help="Chemin local d'un CSV déjà téléchargé. "
        "Sinon, télécharge depuis l'open data Ville de Montréal.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        help="Limiter à N lignes (utile pour tester le pipeline).",
    )
    args = parser.parse_args()

    log.info("Ingestion du rôle d'évaluation Montréal — démarrage…")
    if args.csv:
        log.info("  Source : fichier local %s", args.csv)
    else:
        log.info("  Source : %s", MTL_CSV_URL)
    if args.max_rows:
        log.info("  Limite : %d lignes (test)", args.max_rows)
    else:
        log.info("  Limite : aucune (~500k lignes attendues)")

    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        try:
            result = await ingest_csv(
                db,
                url=MTL_CSV_URL,
                max_rows=args.max_rows,
                csv_path=args.csv,
            )
        except Exception as exc:
            log.error("Échec : %s", exc)
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
