"""Cron quotidien : scrape Kijiji + LesPAC + cleanup vieilles annonces.

À configurer dans Render Dashboard → New → Cron Job, command :
    cd ~/project/src/backend && python -m scripts.rental_scrape_daily

Schedule recommandé : `0 6 * * *` (06h00 UTC = 02h00 EDT, hors heures
de pointe pour éviter de stresser Kijiji/LesPAC).

Comportement :
1. Scrape Kijiji (4 villes × 1 page = ~80-160 annonces)
2. Scrape LesPAC (4 régions × 1 page = ~60-120 annonces)
3. Cleanup : supprime les annonces > 30 jours pour limiter le storage
4. Logs résumés dans stdout (visible dans Render Dashboard → Logs)

Idempotent : déduplication par source_url. Plusieurs runs/jour ne
créent pas de doublons mais rafraîchissent `last_seen_at`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.integrations.centris.scraper import (  # noqa: E402
    CentrisBlocked,
    SEARCH_URLS,
    parse_listings_html,
    try_fetch_search,
    upsert_listings,
)
from app.integrations.rental.kijiji import scrape_kijiji  # noqa: E402
from app.integrations.rental.lespac import scrape_lespac  # noqa: E402
from app.models.rental_listing import RentalListing  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rental_scrape_daily")


async def main() -> int:
    started = time.monotonic()
    log.info("Cron rental_scrape_daily — démarrage…")

    async with AsyncSessionLocal() as db:
        # 1. Kijiji
        try:
            r1 = await scrape_kijiji(
                db,
                max_pages_per_city=1,
                max_listings_per_run=40,
            )
            await db.commit()
            log.info(
                "Kijiji : seen=%s new=%s updated=%s",
                r1.get("listings_seen"),
                r1.get("listings_new"),
                r1.get("listings_updated"),
            )
        except Exception as exc:
            log.exception("Kijiji failed: %s", exc)

        # 2. LesPAC
        try:
            r2 = await scrape_lespac(
                db,
                max_pages_per_city=1,
                max_listings_per_run=40,
            )
            await db.commit()
            log.info(
                "LesPAC : seen=%s new=%s updated=%s",
                r2.get("listings_seen"),
                r2.get("listings_new"),
                r2.get("listings_updated"),
            )
        except Exception as exc:
            log.exception("LesPAC failed: %s", exc)

        # 3. Centris (multi-logements à vendre)
        for cat in ("multiplex_2_5", "immeuble_residentiel_6_plus"):
            try:
                html = await try_fetch_search(SEARCH_URLS[cat], page=1)
                listings = parse_listings_html(html)
                if listings:
                    r = await upsert_listings(db, listings, cat)
                    await db.commit()
                    log.info(
                        "Centris %s : new=%s updated=%s",
                        cat,
                        r["new"],
                        r["updated"],
                    )
                else:
                    log.info("Centris %s : 0 listings parsed", cat)
            except CentrisBlocked as exc:
                log.warning(
                    "Centris %s bloqué par Cloudflare : %s — paste "
                    "manuel requis",
                    cat,
                    exc,
                )
            except Exception as exc:
                log.exception("Centris %s failed: %s", cat, exc)

        # 4. Cleanup : annonces > 30 jours
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            res = await db.execute(
                delete(RentalListing).where(
                    RentalListing.scraped_at < cutoff
                )
            )
            await db.commit()
            log.info("Cleanup : %d vieilles annonces supprimées", res.rowcount)
        except Exception as exc:
            log.exception("Cleanup failed: %s", exc)

    elapsed = time.monotonic() - started
    log.info("✓ Terminé en %.1f s", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
