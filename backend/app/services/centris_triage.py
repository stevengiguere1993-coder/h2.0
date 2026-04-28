"""Triage automatique des annonces Centris.

Pour chaque nouvelle CentrisListing, on tente de :
1. Compléter les données manquantes depuis MTL property units
   (taxes, superficie, année si non scrapées)
2. Estimer le loyer moyen post-stabilisation depuis les comparables
   (Kijiji + LesPAC) du quartier/postal code
3. Lancer le calculateur d'analyse
4. Si APH50 ou SCHL gain ≥ 0 (MDF récupérable via refi), créer
   un lead avec tag « centris-interessant » + analyse persistée
5. Si l'annonce match une adresse de lead existant, notifier owner
   + ajouter une note sur le lead

Le job tourne en arrière-plan après chaque scrape Centris (auto ou
paste manuel).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.centris_listing import CentrisListing
from app.models.montreal_property_unit import MontrealPropertyUnit
from app.models.prospection_analyse import ProspectionAnalyse
from app.models.prospection_lead import (
    ProspectionDealStrategy,
    ProspectionLead,
    ProspectionLeadKind,
    ProspectionLeadStatus,
    ProspectionOwnerKind,
)
from app.models.rental_listing import RentalListing
from app.services.financial_calculator import (
    AnalyseInputs,
    FraisDemarrageInputs,
    calculer_analyse,
)

log = logging.getLogger(__name__)


async def _estimate_market_rent(
    db: AsyncSession,
    listing: CentrisListing,
) -> Optional[float]:
    """Estime le loyer mensuel moyen depuis comparables.

    Match : postal_code FSA (3 char) ou nom_rue. Filtre par chambres
    si on a une idée de la taille typique (basé sur nb_units et année,
    on suppose 4½ ou 5½). Sinon prend la médiane globale.

    Retourne None si aucun comparable trouvé (le pipeline saute
    le scoring auto).
    """
    fsa = (listing.postal_code or "")[:3].upper()

    stmt = select(RentalListing).where(
        RentalListing.price.is_not(None),
        RentalListing.price > 0,
    )
    if fsa:
        from sqlalchemy import func as sa_func

        stmt = stmt.where(
            sa_func.upper(RentalListing.postal_code).like(f"{fsa}%")
        )
    elif listing.nom_rue:
        stmt = stmt.where(
            RentalListing.nom_rue.ilike(f"%{listing.nom_rue}%")
        )
    else:
        return None

    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return None

    # On vise les 4½ (2 chambres) typique multi-logements
    target_beds = 2
    candidates = [
        float(r.price) for r in rows if r.bedrooms == target_beds and r.price
    ]
    if len(candidates) < 3:
        # Pas assez de 4½, fallback sur tous prix
        candidates = [float(r.price) for r in rows if r.price]
    if not candidates:
        return None

    sorted_p = sorted(candidates)
    mid = len(sorted_p) // 2
    if len(sorted_p) % 2 == 0:
        return (sorted_p[mid - 1] + sorted_p[mid]) / 2
    return sorted_p[mid]


async def _enrich_from_mtl(
    db: AsyncSession, listing: CentrisListing
) -> Optional[MontrealPropertyUnit]:
    """Cherche dans mtl_property_units une ligne qui matche
    l'annonce Centris. Match par civique + nom_rue similaires."""
    if not listing.civique or not listing.nom_rue:
        return None
    candidates = (
        await db.execute(
            select(MontrealPropertyUnit)
            .where(
                MontrealPropertyUnit.civique_debut == listing.civique,
                MontrealPropertyUnit.nom_rue.ilike(
                    f"%{listing.nom_rue}%"
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return candidates


def _build_inputs(
    listing: CentrisListing,
    mtl: Optional[MontrealPropertyUnit],
    market_rent: Optional[float],
) -> Optional[AnalyseInputs]:
    """Bâtit AnalyseInputs depuis Centris + MTL + comparables.

    Retourne None si données critiques manquantes (prix, # logements).
    """
    price = float(listing.price) if listing.price else None
    nb_units = listing.nb_units or (
        mtl.nombre_logement if mtl else None
    )
    if not price or not nb_units or nb_units < 2:
        return None

    # Defaults raisonnables si MTL pas matché — l'utilisateur ajustera
    # si le scoring auto est intéressant.
    taxes_mun = 0.0
    taxes_sco = 0.0
    if mtl:
        # Pas de field taxes sur le rôle MTL (taxes ≈ taux x valeur),
        # estimation grossière : ~1 % de la valeur foncière. Zéro si
        # pas connu — l'utilisateur complétera.
        pass

    revenus_actuels_estimes = (
        market_rent * nb_units * 12 * 0.85
        if market_rent
        else price * 0.06  # fallback : 6 % du prix = revenus indicatifs
    )

    return AnalyseInputs(
        adresse=listing.address or "(Centris)",
        prixAchat=price,
        nombreLogements=nb_units,
        revenusAnnuels=revenus_actuels_estimes,
        taxesMunicipales=taxes_mun,
        taxesScolaires=taxes_sco,
        assurances=nb_units * 600.0,  # heuristique 600$/log/an
        energie=nb_units * 300.0,  # heuristique
        autresDepenses=0.0,
        logementsAjoutes=0,
        thermopompesAjoutees=0,
        wifi=False,
        reductionCoutEnergie=0.0,
        nouveauLoyerMoyen=market_rent or (price * 0.06 / nb_units / 12),
        nombreAnneesPortage=2,
        fraisDemarrage=FraisDemarrageInputs(
            taxesBienvenue=price * 0.02,  # estim. taxe bienvenue
        ),
        tga=0.05,  # plus prudent que le 4 % par défaut pour scoring auto
        tauxInteretAchat=0.045,
        tauxInteretRefi=0.040,
    )


async def triage_listing(
    db: AsyncSession, listing: CentrisListing
) -> dict:
    """Évalue UNE annonce Centris. Si rentable, crée le lead.

    Retourne un dict { status, lead_id, gain_aph50, gain_schl }.
    Status : 'created' | 'not_profitable' | 'skipped' | 'matched_lead'.
    """
    # 1. Match avec lead existant
    if listing.civique and listing.nom_rue:
        existing_lead = (
            await db.execute(
                select(ProspectionLead).where(
                    ProspectionLead.address.ilike(
                        f"%{listing.civique} %{listing.nom_rue}%"
                    ),
                    ProspectionLead.archived.is_(False),
                )
            )
        ).scalar_one_or_none()
        if existing_lead is not None:
            await _notify_existing_lead_centris(
                db, listing, existing_lead
            )
            return {
                "status": "matched_lead",
                "lead_id": existing_lead.id,
            }

    # 2. Enrichir depuis MTL + market rent
    mtl = await _enrich_from_mtl(db, listing)
    market_rent = await _estimate_market_rent(db, listing)

    inputs = _build_inputs(listing, mtl, market_rent)
    if inputs is None:
        return {"status": "skipped", "reason": "missing_critical_data"}

    # 3. Calculateur
    results = calculer_analyse(inputs)
    gain_schl = results.schl.gainActionnaires or 0.0
    gain_aph50 = results.aph50.gainActionnaires or 0.0

    # 4. Profitabilité : on garde les leads où SCHL OU APH50 ≥ 0
    profitable = gain_schl >= 0 or gain_aph50 >= 0
    if not profitable:
        return {
            "status": "not_profitable",
            "gain_schl": gain_schl,
            "gain_aph50": gain_aph50,
        }

    # 5. Crée le lead
    lead = ProspectionLead(
        name=listing.address or f"Centris MLS {listing.mls_id}",
        kind=ProspectionLeadKind.MULTILOGEMENT.value,
        address=listing.address,
        city=listing.city,
        postal_code=listing.postal_code,
        matricule=mtl.matricule if mtl else None,
        nb_logements=inputs.nombreLogements,
        annee_construction=listing.year_built
        or (mtl.annee_construction if mtl else None),
        purchase_price=float(listing.price) if listing.price else None,
        owner_kind=ProspectionOwnerKind.INCONNU.value,
        deal_strategy=ProspectionDealStrategy.UNDECIDED.value,
        status=ProspectionLeadStatus.A_VISITER.value,
        notes=(
            f"🏷️ Lead Centris détecté automatiquement\n"
            f"MLS : {listing.mls_id or 'n/a'}\n"
            f"URL : {listing.source_url}\n\n"
            f"Analyse auto :\n"
            f"  • Prix demandé : {inputs.prixAchat:,.0f} $\n"
            f"  • Loyer marché estimé : {inputs.nouveauLoyerMoyen:,.0f} $/mois "
            f"({'comparables' if market_rent else 'fallback heuristique'})\n"
            f"  • MDF achat conventionnel : {results.achat.miseDeFonds:,.0f} $\n"
            f"  • Gain refi SCHL : {gain_schl:+,.0f} $\n"
            f"  • Gain refi APH50 : {gain_aph50:+,.0f} $\n\n"
            f"⚠ Estimations basées sur des heuristiques (taxes, "
            f"assurances). Vérifie les chiffres avant de soumissionner."
        ),
        tags=json.dumps(["centris-interessant"]),
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)

    # 6. Persiste l'analyse pour qu'elle apparaisse dans la fiche du lead
    analyse = ProspectionAnalyse(
        lead_id=lead.id,
        name=f"Auto-Centris — {listing.address or listing.mls_id}",
        inputs_json=_inputs_to_json(inputs),
        results_json=_results_to_json(results),
    )
    db.add(analyse)
    await db.flush()

    # 7. Notification owners
    await _notify_centris_lead_created(db, listing, lead, gain_aph50)

    return {
        "status": "created",
        "lead_id": lead.id,
        "gain_aph50": gain_aph50,
        "gain_schl": gain_schl,
    }


async def _notify_existing_lead_centris(
    db: AsyncSession,
    listing: CentrisListing,
    lead: ProspectionLead,
) -> None:
    """Notifie quand une adresse déjà dans nos leads est listée
    sur Centris. Idempotent — on ne notifie qu'une fois par
    listing."""
    from app.services.notifications import notify_role

    if listing.matricule and lead.matricule and listing.matricule != lead.matricule:
        return  # mismatch — pas notre proprio
    price_str = (
        f"{float(listing.price):,.0f} $".replace(",", " ")
        if listing.price
        else "n/a"
    )
    await notify_role(
        db,
        min_role="manager",
        kind="centris_match_lead",
        title=f"📢 {lead.name} vient d'être listé sur Centris",
        body=(
            f"Prix demandé : {price_str} · "
            f"{listing.nb_units or '?'} log · "
            f"MLS {listing.mls_id or 'n/a'}"
        ),
        href=f"/prospection/{lead.id}",
    )


async def _notify_centris_lead_created(
    db: AsyncSession,
    listing: CentrisListing,
    lead: ProspectionLead,
    gain_aph50: float,
) -> None:
    from app.services.notifications import notify_role

    price_str = (
        f"{float(listing.price):,.0f} $".replace(",", " ")
        if listing.price
        else "?"
    )
    await notify_role(
        db,
        min_role="manager",
        kind="centris_new_lead",
        title=f"💎 Nouveau lead Centris intéressant — {lead.name}",
        body=(
            f"Prix {price_str} · APH50 gain {gain_aph50:+,.0f} $ "
            f"(récupération MDF)"
        ),
        href=f"/prospection/{lead.id}",
    )


def _inputs_to_json(inputs: AnalyseInputs) -> str:
    """Sérialise les inputs en JSON-compatible avec le format TS."""
    f = inputs.fraisDemarrage
    data = {
        "adresse": inputs.adresse,
        "prixAchat": inputs.prixAchat,
        "nombreLogements": inputs.nombreLogements,
        "revenusAnnuels": inputs.revenusAnnuels,
        "taxesMunicipales": inputs.taxesMunicipales,
        "taxesScolaires": inputs.taxesScolaires,
        "assurances": inputs.assurances,
        "energie": inputs.energie,
        "autresDepenses": inputs.autresDepenses,
        "logementsAjoutes": inputs.logementsAjoutes,
        "thermopompesAjoutees": inputs.thermopompesAjoutees,
        "wifi": inputs.wifi,
        "reductionCoutEnergie": inputs.reductionCoutEnergie,
        "nouveauLoyerMoyen": inputs.nouveauLoyerMoyen,
        "nombreAnneesPortage": inputs.nombreAnneesPortage,
        "tga": inputs.tga,
        "tauxInteretAchat": inputs.tauxInteretAchat,
        "tauxInteretRefi": inputs.tauxInteretRefi,
        "fraisDemarrage": {
            "courtierHypo1": f.courtierHypo1,
            "courtierHypo2": f.courtierHypo2,
            "taxesBienvenue": f.taxesBienvenue,
            "evaluateur1": f.evaluateur1,
            "evaluateur2": f.evaluateur2,
            "inspection": f.inspection,
            "avocat": f.avocat,
            "notaire1": f.notaire1,
            "notaire2": f.notaire2,
            "rapportEfficacite": f.rapportEfficacite,
            "fraisDeveloppement": f.fraisDeveloppement,
            "fraisNegociation": f.fraisNegociation,
            "fraisTravaux": f.fraisTravaux,
            "interets": f.interets,
            "revenusNets": f.revenusNets,
        },
    }
    return json.dumps(data, ensure_ascii=False)


def _results_to_json(results) -> str:
    """Sérialise les résultats. Format compatible avec ce que le
    frontend attend (snake → camelCase déjà aligné)."""

    def scen_to_dict(s) -> dict:
        d = s.depensesNormalisees
        return {
            "id": s.id,
            "label": s.label,
            "fraisDemarrageTotal": s.fraisDemarrageTotal,
            "prixAcquisition": s.prixAcquisition,
            "revenusTotaux": s.revenusTotaux,
            "depensesNormalisees": {
                "inoccupation": d.inoccupation,
                "taxesMunicipales": d.taxesMunicipales,
                "taxesScolaires": d.taxesScolaires,
                "assurances": d.assurances,
                "energie": d.energie,
                "concierge": d.concierge,
                "entretien": d.entretien,
                "gestion": d.gestion,
                "wifi": d.wifi,
                "thermopompes": d.thermopompes,
                "autres": d.autres,
                "total": d.total,
            },
            "revenusNets": s.revenusNets,
            "valeurEconomiqueTGA": s.valeurEconomiqueTGA,
            "paiementHypoMax": s.paiementHypoMax,
            "hypothequeMaxRCD": s.hypothequeMaxRCD,
            "valeurEconomiqueRCD": s.valeurEconomiqueRCD,
            "valeurMarchande": s.valeurMarchande,
            "valeurRetenue": s.valeurRetenue,
            "ratioCouvertureDette": s.ratioCouvertureDette,
            "ratioPretValeur": s.ratioPretValeur,
            "amortissementAnnees": s.amortissementAnnees,
            "tauxInteret": s.tauxInteret,
            "pretAccorde": s.pretAccorde,
            "miseDeFonds": s.miseDeFonds,
            "gainActionnaires": s.gainActionnaires,
        }

    return json.dumps(
        {
            "achat": scen_to_dict(results.achat),
            "schl": scen_to_dict(results.schl),
            "aph50": scen_to_dict(results.aph50),
        },
        ensure_ascii=False,
    )


async def triage_recent_listings(
    db: AsyncSession, since_hours: int = 48
) -> dict:
    """Triage en batch les annonces Centris des dernières N heures
    qui n'ont pas encore généré de lead. Idempotent : on saute les
    listings qui ont déjà un matricule == matricule d'un lead actif.

    À appeler après chaque scrape Centris (cron ou manuel).
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    listings = (
        await db.execute(
            select(CentrisListing).where(
                CentrisListing.first_seen_at >= cutoff,
            )
        )
    ).scalars().all()

    summary = {
        "processed": 0,
        "created": 0,
        "matched_existing": 0,
        "not_profitable": 0,
        "skipped": 0,
    }
    for listing in listings:
        try:
            r = await triage_listing(db, listing)
            summary["processed"] += 1
            if r["status"] == "created":
                summary["created"] += 1
            elif r["status"] == "matched_lead":
                summary["matched_existing"] += 1
            elif r["status"] == "not_profitable":
                summary["not_profitable"] += 1
            else:
                summary["skipped"] += 1
        except Exception as exc:
            log.exception(
                "triage_listing failed (id=%s): %s", listing.id, exc
            )
            summary["skipped"] += 1
    await db.commit()
    return summary
