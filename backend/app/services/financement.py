"""Financement d'un immeuble — service (Phil 2026-10-16).

- ``rent_roll`` : une ligne par unité depuis les baux ENREGISTRÉS (bail
  standard en vigueur, prochain bail), une section à part pour les baux
  PARALLÈLES (sous-location, bail principal d'un exploitant : vrais
  contrats hors du quotidien), totaux par catégorie, et une colonne
  « projection » facultative, toujours identifiée comme telle.
- exports : lignes CSV/Excel et PDF (reportlab), avec la provenance des
  montants dans le pied de page.
- ``documents_immeuble`` + ``paquet_pdf`` : les pièces du dossier
  (baux signés, avis, pièces importées) fusionnées en un seul PDF.
- checklist par type de dossier, projection par défaut, tableau de bord.

Règle de conception : aucun montant « pour la banque ». Les chiffres
viennent des baux ; la projection est une colonne séparée, marquée.
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.financement import (
    FINANCEMENT_TYPES,
    Financement,
    FinancementJournal,
    FinancementPiece,
)
from app.models.immobilier import (
    Bail,
    BailStatus,
    ImmDocument,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
    est_bail_parallele,
)

log = logging.getLogger(__name__)

#: Taille maximale d'un paquet PDF (au-delà : 413 explicite).
MAX_PAQUET_BYTES = 150 * 1024 * 1024
#: Libellés des types de bail parallèle (menus + exports).
PARALLELE_TYPE_LABELS: dict[str, str] = {
    "sous_location": "Sous-location",
    "bail_principal": "Bail principal (exploitant)",
    "colocation": "Colocation",
    "autre": "Autre",
}
STATUT_LOGEMENT_LABELS: dict[str, str] = {
    "occupe": "Occupé",
    "vacant": "Vacant",
    "reserve": "Réservé",
    "hors_location": "Hors location",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _cle_tri(numero: Optional[str]) -> tuple:
    try:
        from app.services.locatif_chambres import cle_tri_numero

        return cle_tri_numero(numero)
    except Exception:  # noqa: BLE001
        s = str(numero or "")
        m = re.match(r"^\s*(\d+)(.*)$", s)
        return (0, int(m.group(1)), m.group(2).strip().lower()) if m else (1, 0, s.lower())


def _couvre(b: Bail, jour: date) -> bool:
    """Le bail couvre-t-il ``jour`` ? (au mois = sans égard à la fin)."""
    if b.date_debut is None or b.date_debut > jour:
        return False
    if b.au_mois:
        return True
    return b.date_fin is None or b.date_fin >= jour


def inclusions_de(b: Bail) -> list[str]:
    out = []
    if b.chauffage_inclus:
        out.append("chauffage")
    if b.eau_chaude_inclus:
        out.append("eau chaude")
    if b.electricite_inclus:
        out.append("électricité")
    if b.internet_inclus:
        out.append("internet")
    return out


# ─── Rent roll ────────────────────────────────────────────────────────


@dataclass
class RentRoll:
    immeuble: dict[str, Any]
    a_date: date
    lignes: list[dict[str, Any]] = field(default_factory=list)
    paralleles: list[dict[str, Any]] = field(default_factory=list)
    totaux: dict[str, Any] = field(default_factory=dict)
    projection: Optional[dict[str, Any]] = None
    genere_le: datetime = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "immeuble": self.immeuble,
            "a_date": self.a_date.isoformat(),
            "lignes": self.lignes,
            "paralleles": self.paralleles,
            "totaux": self.totaux,
            "projection": self.projection,
            "genere_le": self.genere_le.isoformat(),
        }


def _charger_projection(txt: Optional[str]) -> dict[str, Any]:
    if not txt:
        return {"logements": {}, "hypotheses": {}}
    try:
        d = json.loads(txt)
    except Exception:  # noqa: BLE001
        return {"logements": {}, "hypotheses": {}}
    if not isinstance(d, dict):
        return {"logements": {}, "hypotheses": {}}
    d.setdefault("logements", {})
    d.setdefault("hypotheses", {})
    if not isinstance(d["logements"], dict):
        d["logements"] = {}
    if not isinstance(d["hypotheses"], dict):
        d["hypotheses"] = {}
    return d


async def rent_roll(
    db: AsyncSession,
    immeuble_id: int,
    *,
    inclure_standards: bool = True,
    inclure_paralleles: bool = True,
    projection: Optional[dict[str, Any]] = None,
    a_date: Optional[date] = None,
) -> RentRoll:
    """Photo de l'immeuble à ``a_date`` (défaut aujourd'hui) depuis les baux
    enregistrés. ``projection`` = {"logements": {id: {loyer, source,
    note}}, "hypotheses": {...}} → colonne « projection » (séparée)."""
    jour = a_date or date.today()
    im = await db.get(Immeuble, immeuble_id)
    if im is None:
        raise ValueError("Immeuble introuvable.")
    logements = (
        await db.execute(select(Logement).where(Logement.immeuble_id == immeuble_id))
    ).scalars().all()
    logements.sort(key=lambda l: _cle_tri(l.numero))
    ids = [l.id for l in logements]
    baux: list[Bail] = []
    if ids:
        baux = (await db.execute(select(Bail).where(Bail.logement_id.in_(ids)))).scalars().all()
    loc_ids = {b.locataire_id for b in baux if b.locataire_id}
    locs: dict[int, Locataire] = {}
    if loc_ids:
        for lo in (await db.execute(select(Locataire).where(Locataire.id.in_(loc_ids)))).scalars().all():
            locs[lo.id] = lo
    par_log: dict[int, list[Bail]] = {}
    for b in baux:
        par_log.setdefault(b.logement_id, []).append(b)

    proj = _charger_projection(json.dumps(projection)) if isinstance(projection, dict) else {"logements": {}, "hypotheses": {}}
    proj_logs = proj.get("logements") or {}
    avec_projection = bool(proj_logs)

    lignes: list[dict[str, Any]] = []
    paralleles: list[dict[str, Any]] = []
    tot_std = 0.0
    tot_par = 0.0
    tot_proj = 0.0
    nb_occ = nb_vac = nb_res = nb_hors = 0

    for lg in logements:
        liste = par_log.get(lg.id, [])
        standards = [b for b in liste if not est_bail_parallele(b)]
        pars = [b for b in liste if est_bail_parallele(b)]
        courant = None
        for b in standards:
            if b.status == BailStatus.ACTIF.value and _couvre(b, jour):
                if courant is None or (b.date_debut or date.min) > (courant.date_debut or date.min):
                    courant = b
        prochain = None
        for b in standards:
            if b.id == (courant.id if courant else None):
                continue
            if b.status == BailStatus.PROPOSE.value or (
                b.status == BailStatus.ACTIF.value and b.date_debut and b.date_debut > jour
            ):
                if prochain is None or (b.date_debut or date.max) < (prochain.date_debut or date.max):
                    prochain = b
        par_vigueur = [b for b in pars if b.status == BailStatus.PARALLELE.value]

        if lg.status == LogementStatus.HORS_LOC.value and courant is None:
            occupation = "hors_location"
            nb_hors += 1
        elif courant is not None:
            occupation = "occupe"
            nb_occ += 1
        elif par_vigueur:
            occupation = "parallele_seulement"
            nb_occ += 1
        elif prochain is not None:
            occupation = "reserve"
            nb_res += 1
        else:
            occupation = "vacant"
            nb_vac += 1

        loyer = _f(courant.loyer_mensuel) if courant else None
        if loyer:
            tot_std += loyer
        lo = locs.get(courant.locataire_id) if courant else None
        ligne: dict[str, Any] = {
            "logement_id": lg.id,
            "numero": lg.numero,
            "etage": lg.etage,
            "nb_pieces": _f(lg.nb_pieces_decimal),
            "nb_chambres": lg.nb_chambres,
            "superficie_pi2": _f(lg.superficie_pi2),
            "statut_logement": lg.status,
            "occupation": occupation,
            "en_chambres": bool(getattr(lg, "location_en_chambres", False)),
            "bail_id": courant.id if courant else None,
            "locataire_id": courant.locataire_id if courant else None,
            "locataire": (lo.full_name if lo else None),
            "loyer": loyer,
            "inclusions": inclusions_de(courant) if courant else [],
            "date_debut": courant.date_debut.isoformat() if courant and courant.date_debut else None,
            "date_fin": courant.date_fin.isoformat() if courant and courant.date_fin else None,
            "au_mois": bool(courant.au_mois) if courant else None,
            "jour_echeance": courant.jour_echeance if courant else None,
            "depot": _f(courant.depot_garantie) if courant else None,
            "document_signe": bool(courant.document_id) if courant else None,
            "loyer_demande": _f(lg.loyer_demande),
            "nb_paralleles": len(par_vigueur),
            "categorie": "standard",
        }
        if prochain is not None:
            plo = locs.get(prochain.locataire_id)
            ligne["prochain"] = {
                "bail_id": prochain.id,
                "locataire": plo.full_name if plo else None,
                "date_debut": prochain.date_debut.isoformat() if prochain.date_debut else None,
                "loyer": _f(prochain.loyer_mensuel),
                "statut": prochain.status,
            }
        if avec_projection:
            p = proj_logs.get(str(lg.id)) or proj_logs.get(lg.id) or {}
            lp = _f(p.get("loyer")) if isinstance(p, dict) else None
            if lp is None:
                lp = loyer if loyer is not None else _f(lg.loyer_demande)
                source = "bail" if loyer is not None else ("demande" if lp is not None else None)
            else:
                source = (p.get("source") if isinstance(p, dict) else None) or "manuel"
            ligne["projection"] = {"loyer": lp, "source": source, "note": (p.get("note") if isinstance(p, dict) else None)}
            if lp:
                tot_proj += lp
        lignes.append(ligne)

        if inclure_paralleles:
            for b in sorted(pars, key=lambda x: (x.status != BailStatus.PARALLELE.value, x.date_debut or date.min)):
                if b.status in (BailStatus.TERMINE.value, BailStatus.RESILIE.value):
                    continue
                plo = locs.get(b.locataire_id)
                lp_ = _f(b.loyer_mensuel)
                en_vigueur = b.status == BailStatus.PARALLELE.value
                if en_vigueur and lp_:
                    tot_par += lp_
                paralleles.append({
                    "bail_id": b.id,
                    "logement_id": lg.id,
                    "numero": lg.numero,
                    "locataire_id": b.locataire_id,
                    "locataire": plo.full_name if plo else None,
                    "locateur_bail": b.parallele_locateur,
                    "type": b.parallele_type,
                    "type_label": PARALLELE_TYPE_LABELS.get(b.parallele_type or "", b.parallele_type or ""),
                    "loyer": lp_,
                    "inclusions": inclusions_de(b),
                    "date_debut": b.date_debut.isoformat() if b.date_debut else None,
                    "date_fin": b.date_fin.isoformat() if b.date_fin else None,
                    "au_mois": bool(b.au_mois),
                    "statut": b.status,
                    "en_vigueur": en_vigueur,
                    "echu": bool(b.date_fin and b.date_fin < jour and not b.au_mois),
                    "document_signe": bool(b.document_id),
                    "note": b.parallele_note,
                    "categorie": "parallele",
                })

    nb = len(logements)
    totaux = {
        "nb_unites": nb,
        "nb_occupees": nb_occ,
        "nb_vacantes": nb_vac,
        "nb_reservees": nb_res,
        "nb_hors_location": nb_hors,
        "taux_occupation_pct": round(100.0 * nb_occ / nb, 1) if nb else None,
        "mensuel_standard": round(tot_std, 2),
        "annuel_standard": round(tot_std * 12, 2),
        "nb_paralleles": sum(1 for p in paralleles if p["en_vigueur"]),
        "mensuel_paralleles": round(tot_par, 2),
        "annuel_paralleles": round(tot_par * 12, 2),
    }
    if avec_projection:
        vac = _f((proj.get("hypotheses") or {}).get("vacance_pct")) or 0.0
        totaux["projection_mensuelle"] = round(tot_proj, 2)
        totaux["projection_annuelle"] = round(tot_proj * 12 * (1 - vac / 100.0), 2)
        totaux["projection_vacance_pct"] = vac
        totaux["ecart_projection_pct"] = (
            round(100.0 * (tot_proj - tot_std) / tot_std, 1) if tot_std else None
        )
    if not inclure_standards:
        # Export « baux parallèles seulement » : la section standard et ses
        # totaux disparaissent (le document le dit dans son titre).
        lignes = []
        totaux["mensuel_standard"] = 0.0
        totaux["annuel_standard"] = 0.0
        totaux.pop("projection_mensuelle", None)
        totaux.pop("projection_annuelle", None)
        totaux.pop("ecart_projection_pct", None)
        avec_projection = False
    totaux["categories"] = [c for c, ok in (("standard", inclure_standards), ("parallele", inclure_paralleles)) if ok]
    return RentRoll(
        immeuble={
            "id": im.id, "nom": im.name, "adresse": im.address, "ville": im.city,
            "code_postal": im.postal_code, "annee_construction": im.annee_construction,
            "nb_logements": im.nb_logements or nb,
        },
        a_date=jour, lignes=lignes, paralleles=paralleles, totaux=totaux,
        projection=(proj if avec_projection else None),
    )


# ─── Exports tabulaires ────────────────────────────────────────────────

COLONNES_RENT_ROLL = [
    "Catégorie", "Unité", "Pièces", "Occupation", "Locataire", "Locateur du bail",
    "Type (parallèle)", "Loyer mensuel", "Chauffage", "Eau chaude", "Électricité", "Internet",
    "Début", "Fin", "Au mois", "Payable le", "Dépôt", "Bail signé", "Prochain locataire",
    "Prochain début", "Prochain loyer",
]
COLONNES_PROJECTION = ["Projection — loyer (estimation)", "Projection — source"]


def rent_roll_tableau(rr: RentRoll) -> tuple[list[str], list[list[Any]]]:
    """Colonnes + lignes pour CSV/Excel : baux standards, puis baux
    parallèles (catégorie en première colonne), puis totaux par catégorie.
    La projection, si présente, occupe des colonnes séparées."""
    avec_proj = rr.projection is not None
    colonnes = list(COLONNES_RENT_ROLL) + (COLONNES_PROJECTION if avec_proj else [])
    rows: list[list[Any]] = []

    def oui_non(v: Any) -> Optional[str]:
        return None if v is None else ("oui" if v else "non")

    for l in rr.lignes:
        inc = set(l.get("inclusions") or [])
        row = [
            "Standard", l["numero"], l.get("nb_pieces"),
            STATUT_LOGEMENT_LABELS.get(l["occupation"], "Occupé (bail parallèle)" if l["occupation"] == "parallele_seulement" else l["occupation"]),
            l.get("locataire"), None, None, l.get("loyer"),
            oui_non("chauffage" in inc) if l.get("bail_id") else None,
            oui_non("eau chaude" in inc) if l.get("bail_id") else None,
            oui_non("électricité" in inc) if l.get("bail_id") else None,
            oui_non("internet" in inc) if l.get("bail_id") else None,
            l.get("date_debut"), l.get("date_fin"), oui_non(l.get("au_mois")), l.get("jour_echeance"),
            l.get("depot"), oui_non(l.get("document_signe")),
            (l.get("prochain") or {}).get("locataire"), (l.get("prochain") or {}).get("date_debut"),
            (l.get("prochain") or {}).get("loyer"),
        ]
        if avec_proj:
            p = l.get("projection") or {}
            row += [p.get("loyer"), p.get("source")]
        rows.append(row)
    for p in rr.paralleles:
        inc = set(p.get("inclusions") or [])
        row = [
            "Parallèle" + ("" if p["en_vigueur"] else f" ({p['statut']})"), p["numero"], None,
            "En vigueur" if p["en_vigueur"] else ("En signature" if p["statut"] == "propose" else p["statut"]),
            p.get("locataire"), p.get("locateur_bail"), p.get("type_label"), p.get("loyer"),
            oui_non("chauffage" in inc), oui_non("eau chaude" in inc), oui_non("électricité" in inc), oui_non("internet" in inc),
            p.get("date_debut"), p.get("date_fin"), oui_non(p.get("au_mois")), None, None, oui_non(p.get("document_signe")),
            None, None, None,
        ]
        if avec_proj:
            row += [None, None]
        rows.append(row)
    t = rr.totaux
    vide = [None] * (len(colonnes) - 8)
    if "standard" in (t.get("categories") or ["standard"]):
        rows.append(["TOTAL baux standards", f"{t['nb_occupees']} occupées / {t['nb_unites']} unités", None, None, None, None, None, t["mensuel_standard"]] + vide)
    if rr.paralleles:
        rows.append(["TOTAL baux parallèles (en vigueur)", f"{t['nb_paralleles']} bail(s)", None, None, None, None, None, t["mensuel_paralleles"]] + vide)
    if avec_proj:
        rows.append(["PROJECTION (estimation, pas un bail)", f"vacance {t.get('projection_vacance_pct', 0)} %", None, None, None, None, None, t.get("projection_mensuelle")] + vide)
    return colonnes, rows


# ─── PDF ───────────────────────────────────────────────────────────────


def _money(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.2f} $".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


def rent_roll_pdf(rr: RentRoll, *, titre: Optional[str] = None, preteur: Optional[str] = None) -> bytes:
    """Rent roll en PDF (paysage) : en-tête immeuble, tableau des baux
    standards, totaux, section « Baux parallèles », colonne projection si
    présente, et la provenance des montants en pied de page."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(LETTER), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=titre or f"Rent roll — {rr.immeuble['nom']}",
    )
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading1"], fontSize=15, spaceAfter=2)
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8, leading=10)
    cell = ParagraphStyle("c", parent=styles["Normal"], fontSize=7.5, leading=9)
    im = rr.immeuble
    avec_proj = rr.projection is not None
    cats = rr.totaux.get("categories") or ["standard", "parallele"]
    if titre is None:
        if cats == ["parallele"]:
            titre = f"Rent roll — baux parallèles — {im['nom']}"
        elif cats == ["standard"]:
            titre = f"Rent roll — baux standards — {im['nom']}"
        else:
            titre = f"Rent roll — {im['nom']}"
    story: list[Any] = [
        Paragraph(titre, h),
        Paragraph(
            f"{im['adresse']}{', ' + im['ville'] if im.get('ville') else ''}{' ' + im['code_postal'] if im.get('code_postal') else ''}"
            f" · {im.get('nb_logements') or len(rr.lignes)} unités"
            f"{' · construit en ' + str(im['annee_construction']) if im.get('annee_construction') else ''}"
            f" · situation au {rr.a_date.isoformat()}"
            f"{' · préparé pour ' + preteur if preteur else ''}",
            small,
        ),
        Spacer(1, 4 * mm),
    ]

    def P(v: Any) -> Paragraph:
        return Paragraph("" if v is None else str(v), cell)

    entetes = ["Unité", "Pièces", "Occupation", "Locataire", "Loyer / mois", "Inclusions", "Début", "Fin", "Payable", "Dépôt", "Bail signé"]
    if avec_proj:
        entetes += ["Projection*", "Source"]
    data = [[P(f"<b>{e}</b>") for e in entetes]]
    for l in rr.lignes:
        occ = STATUT_LOGEMENT_LABELS.get(l["occupation"], "Occupé (bail parallèle)" if l["occupation"] == "parallele_seulement" else l["occupation"])
        if l.get("prochain"):
            occ += f"<br/><font size='6'>prochain : {l['prochain'].get('locataire') or '—'} ({l['prochain'].get('date_debut') or '?'})</font>"
        row = [
            P(l["numero"]), P(f"{l['nb_pieces']:g}".replace(".5", "½") if l.get("nb_pieces") else ""), P(occ), P(l.get("locataire") or "—"),
            P(_money(l.get("loyer")) if l.get("loyer") is not None else "—"),
            P(", ".join(l.get("inclusions") or []) or ("—" if l.get("bail_id") else "")),
            P(l.get("date_debut") or ""), P(("au mois" if l.get("au_mois") else l.get("date_fin")) or ""),
            P(f"le {l['jour_echeance']}" if l.get("jour_echeance") else ""), P(_money(l["depot"]) if l.get("depot") else ""),
            P(("oui" if l.get("document_signe") else "non") if l.get("bail_id") else ""),
        ]
        if avec_proj:
            p = l.get("projection") or {}
            row += [P(_money(p.get("loyer")) if p.get("loyer") is not None else "—"), P(p.get("source") or "")]
        data.append(row)
    t = rr.totaux
    tot_row = [P("<b>Total</b>"), P(""), P(f"<b>{t['nb_occupees']} occ. / {t['nb_vacantes']} vac.</b>"), P(""), P(f"<b>{_money(t['mensuel_standard'])}</b>"),
               P(f"annuel {_money(t['annuel_standard'])}"), P(""), P(""), P(""), P(""), P("")]
    if avec_proj:
        tot_row += [P(f"<b>{_money(t.get('projection_mensuelle'))}</b>"), P(f"annuel {_money(t.get('projection_annuelle'))}")]
    data.append(tot_row)
    largeurs = [16, 13, 32, 42, 22, 34, 19, 19, 15, 18, 15] + ([22, 16] if avec_proj else [])
    table = Table(data, colWidths=[w * mm for w in largeurs], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9ca3af")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f3f4f6")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    # L'en-tête de la colonne projection est sur fond ambre : on ne confond pas.
    if avec_proj:
        table.setStyle(TableStyle([("BACKGROUND", (-2, 0), (-1, 0), colors.HexColor("#b45309"))]))
    if "standard" in cats:
        story.append(Paragraph("<b>Baux standards</b> (contrats enregistrés, en vigueur à la date indiquée)", small))
        story.append(Spacer(1, 1.5 * mm))
        story.append(table)

    if rr.paralleles:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(
            "<b>Baux parallèles</b> — sous-locations et baux principaux d'exploitant : contrats réels signés entre "
            "le locateur indiqué et l'occupant, hors de la gestion quotidienne de l'immeuble. Montants tels qu'au bail.",
            small,
        ))
        story.append(Spacer(1, 1.5 * mm))
        ent2 = ["Unité", "Occupant (locataire)", "Locateur du bail", "Type", "Loyer / mois", "Inclusions", "Début", "Fin", "Statut", "Bail signé"]
        d2 = [[P(f"<b>{e}</b>") for e in ent2]]
        for p in rr.paralleles:
            d2.append([
                P(p["numero"]), P(p.get("locataire") or "—"), P(p.get("locateur_bail") or "—"), P(p.get("type_label") or ""),
                P(_money(p.get("loyer"))), P(", ".join(p.get("inclusions") or []) or "—"), P(p.get("date_debut") or ""),
                P(("au mois" if p.get("au_mois") else p.get("date_fin")) or ""),
                P("en vigueur" if p["en_vigueur"] else ("en signature" if p["statut"] == "propose" else p["statut"])),
                P("oui" if p.get("document_signe") else "non"),
            ])
        d2.append([P("<b>Total (en vigueur)</b>"), P(f"<b>{t['nb_paralleles']} bail(s)</b>"), P(""), P(""), P(f"<b>{_money(t['mensuel_paralleles'])}</b>"),
                   P(f"annuel {_money(t['annuel_paralleles'])}"), P(""), P(""), P(""), P("")])
        t2 = Table(d2, colWidths=[w * mm for w in [16, 42, 42, 30, 22, 34, 19, 19, 22, 15]], repeatRows=1)
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4c1d95")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9ca3af")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f5f3ff")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ede9fe")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t2)

    story.append(Spacer(1, 5 * mm))
    pied = (
        f"Produit par Kratos le {rr.genere_le.strftime('%Y-%m-%d %H:%M')} UTC. Tous les montants proviennent des baux "
        "enregistrés dans Kratos (baux standards en vigueur, baux parallèles tels que signés)."
    )
    if avec_proj:
        pied += (
            " * La colonne « Projection » est une ESTIMATION du propriétaire (loyer visé par unité, "
            f"vacance {t.get('projection_vacance_pct', 0)} %) — ce n'est pas un bail et elle n'engage personne."
        )
    story.append(Paragraph(pied, small))
    doc.build(story)
    return buf.getvalue()


# ─── Documents de l'immeuble + paquet PDF ──────────────────────────────


async def documents_immeuble(db: AsyncSession, immeuble_id: int) -> list[dict[str, Any]]:
    """Toutes les pièces (sans le PDF) rattachées à l'immeuble : par
    l'immeuble, ses logements, ses baux ou les locataires de ses baux."""
    logs = (await db.execute(select(Logement.id, Logement.numero).where(Logement.immeuble_id == immeuble_id))).all()
    log_ids = [r[0] for r in logs]
    numero_par_log = {r[0]: r[1] for r in logs}
    baux = (await db.execute(select(Bail).where(Bail.logement_id.in_(log_ids)))).scalars().all() if log_ids else []
    bail_ids = [b.id for b in baux]
    loc_ids = list({b.locataire_id for b in baux if b.locataire_id})
    bail_par_id = {b.id: b for b in baux}
    conds = [ImmDocument.immeuble_id == immeuble_id]
    if log_ids:
        conds.append(ImmDocument.logement_id.in_(log_ids))
    if bail_ids:
        conds.append(ImmDocument.bail_id.in_(bail_ids))
    if loc_ids:
        conds.append(ImmDocument.locataire_id.in_(loc_ids))
    from sqlalchemy import or_

    docs = (
        await db.execute(select(ImmDocument).where(or_(*conds)).order_by(ImmDocument.created_at.desc()))
    ).scalars().all()
    locs: dict[int, str] = {}
    if loc_ids:
        for lo in (await db.execute(select(Locataire).where(Locataire.id.in_(loc_ids)))).scalars().all():
            locs[lo.id] = lo.full_name
    out = []
    for d in docs:
        b = bail_par_id.get(d.bail_id) if d.bail_id else None
        lg_id = d.logement_id or (b.logement_id if b else None)
        out.append({
            "id": d.id, "type": d.type, "titre": d.titre, "source": d.source, "filename": d.filename,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "signed_at": d.signed_at.isoformat() if d.signed_at else None,
            "bail_id": d.bail_id, "logement_id": lg_id, "numero": numero_par_log.get(lg_id) if lg_id else None,
            "locataire_id": d.locataire_id, "locataire": locs.get(d.locataire_id) if d.locataire_id else None,
            "bail_categorie": (getattr(b, "categorie", None) or "standard") if b else None,
            "est_bail_courant": bool(b and b.document_id == d.id),
        })
    return out


def _est_pdf(blob: Optional[bytes]) -> bool:
    return bool(blob) and bytes(blob[:5]) == b"%PDF-"


async def paquet_pdf(
    db: AsyncSession, immeuble_id: int, document_ids: Iterable[int], *, en_tete_pdf: Optional[bytes] = None
) -> tuple[bytes, list[dict[str, Any]]]:
    """Fusionne, dans l'ordre demandé, les PDF des documents de l'immeuble
    (les pièces hors immeuble sont refusées, les images ignorées). Renvoie
    (pdf, rapport par document)."""
    from pypdf import PdfReader, PdfWriter

    permis = {d["id"]: d for d in await documents_immeuble(db, immeuble_id)}
    ids = [int(i) for i in document_ids]
    writer = PdfWriter()
    rapport: list[dict[str, Any]] = []
    taille = 0
    if en_tete_pdf:
        for page in PdfReader(io.BytesIO(en_tete_pdf)).pages:
            writer.add_page(page)
        taille += len(en_tete_pdf)
        rapport.append({"id": 0, "titre": "Rent roll (généré)", "ok": True})
    for did in ids:
        meta = permis.get(did)
        if meta is None:
            rapport.append({"id": did, "titre": None, "ok": False, "raison": "document hors de cet immeuble"})
            continue
        blob = (
            await db.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == did))
        ).scalar_one_or_none()
        if not _est_pdf(blob):
            rapport.append({"id": did, "titre": meta["titre"], "ok": False, "raison": "pas un PDF (image ou vide)"})
            continue
        taille += len(blob)
        if taille > MAX_PAQUET_BYTES:
            rapport.append({"id": did, "titre": meta["titre"], "ok": False, "raison": "paquet trop volumineux"})
            break
        try:
            for page in PdfReader(io.BytesIO(bytes(blob))).pages:
                writer.add_page(page)
            rapport.append({"id": did, "titre": meta["titre"], "ok": True})
        except Exception as exc:  # noqa: BLE001
            rapport.append({"id": did, "titre": meta["titre"], "ok": False, "raison": f"PDF illisible ({type(exc).__name__})"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), rapport


# ─── Checklist, projection, tableau de bord ────────────────────────────

_PIECES_COMMUNES: list[tuple[str, str]] = [
    ("rent_roll", "Rent roll (généré par Kratos)"),
    ("baux", "Baux signés en vigueur"),
    ("avis", "Avis de renouvellement / augmentation de l'année"),
    ("etats_financiers", "États financiers de l'immeuble (2 ans)"),
    ("taxes", "Comptes de taxes municipales et scolaires"),
    ("assurance", "Police d'assurance de l'immeuble"),
    ("identite", "États financiers personnels / corporatifs des emprunteurs"),
    ("organigramme", "Organigramme corporatif et actionnaires"),
]
_PIECES_PAR_TYPE: dict[str, list[tuple[str, str]]] = {
    "refinancement": [("releve_hypothecaire", "Relevé hypothécaire actuel"), ("evaluation", "Évaluation marchande (si demandée)")],
    "renouvellement": [("releve_hypothecaire", "Relevé hypothécaire actuel")],
    "achat": [("offre_achat", "Offre d'achat acceptée"), ("evaluation", "Évaluation marchande"), ("etats_financiers", "États financiers du vendeur")],
    "autre": [],
}


def pieces_defaut(type_dossier: str, *, avec_paralleles: bool = False) -> list[dict[str, Any]]:
    base = list(_PIECES_COMMUNES)
    if avec_paralleles:
        base.insert(2, ("baux_paralleles", "Baux parallèles (sous-location) signés"))
    for t, l in _PIECES_PAR_TYPE.get(type_dossier, []):
        if all(t != x[0] for x in base) or t == "etats_financiers":
            base.append((t, l))
    return [{"type": t, "libelle": l, "requis": True, "ordre": i} for i, (t, l) in enumerate(base)]


def projection_defaut(rr: RentRoll) -> dict[str, Any]:
    """Point de départ d'une projection : le loyer du bail, sinon le loyer
    demandé du logement — toujours marqué par sa source."""
    logs: dict[str, Any] = {}
    for l in rr.lignes:
        if l.get("loyer") is not None:
            logs[str(l["logement_id"])] = {"loyer": l["loyer"], "source": "bail", "note": ""}
        elif l.get("loyer_demande") is not None:
            logs[str(l["logement_id"])] = {"loyer": l["loyer_demande"], "source": "demande", "note": ""}
    return {"logements": logs, "hypotheses": {"vacance_pct": 0}}


async def tableau_de_bord(db: AsyncSession, fin: Financement, rr: RentRoll, pieces: list[FinancementPiece]) -> dict[str, Any]:
    t = rr.totaux
    requises = [p for p in pieces if p.requis]
    fournies = [p for p in requises if p.document_id or p.envoye_le]
    manquantes = [p.libelle for p in requises if not (p.document_id or p.envoye_le)]
    jours = None
    if fin.date_echeance:
        jours = (fin.date_echeance - date.today()).days
    return {
        "reel_mensuel": t["mensuel_standard"],
        "reel_annuel": t["annuel_standard"],
        "paralleles_mensuel": t["mensuel_paralleles"] if fin.inclure_paralleles else 0.0,
        "paralleles_annuel": t["annuel_paralleles"] if fin.inclure_paralleles else 0.0,
        "projection_mensuelle": t.get("projection_mensuelle"),
        "projection_annuelle": t.get("projection_annuelle"),
        "ecart_projection_pct": t.get("ecart_projection_pct"),
        "taux_occupation_pct": t["taux_occupation_pct"],
        "nb_unites": t["nb_unites"],
        "nb_vacantes": t["nb_vacantes"],
        "pieces_requises": len(requises),
        "pieces_fournies": len(fournies),
        "pieces_manquantes": manquantes,
        "jours_avant_echeance": jours,
    }


def resume_financement(fin: Financement, *, pieces: Optional[list[FinancementPiece]] = None) -> dict[str, Any]:
    requises = [p for p in (pieces or []) if p.requis]
    return {
        "id": fin.id,
        "immeuble_id": fin.immeuble_id,
        "hypotheque_id": fin.hypotheque_id,
        "titre": fin.titre,
        "type": fin.type,
        "preteur": fin.preteur,
        "courtier": fin.courtier,
        "montant_demande": _f(fin.montant_demande),
        "taux_pct": _f(fin.taux_pct),
        "terme_mois": fin.terme_mois,
        "amortissement_mois": fin.amortissement_mois,
        "statut": fin.statut,
        "date_depot": fin.date_depot.isoformat() if fin.date_depot else None,
        "date_reponse": fin.date_reponse.isoformat() if fin.date_reponse else None,
        "date_echeance": fin.date_echeance.isoformat() if fin.date_echeance else None,
        "inclure_standards": bool(getattr(fin, "inclure_standards", True)),
        "inclure_paralleles": bool(fin.inclure_paralleles),
        "projection": _charger_projection(fin.projection_json),
        "notes": fin.notes,
        "created_by_email": fin.created_by_email,
        "created_at": fin.created_at.isoformat() if fin.created_at else None,
        "updated_at": fin.updated_at.isoformat() if fin.updated_at else None,
        "nb_pieces_requises": len(requises) if pieces is not None else None,
        "nb_pieces_fournies": sum(1 for p in requises if p.document_id or p.envoye_le) if pieces is not None else None,
    }


def resume_piece(p: FinancementPiece) -> dict[str, Any]:
    return {
        "id": p.id, "financement_id": p.financement_id, "type": p.type, "libelle": p.libelle,
        "requis": bool(p.requis), "ordre": p.ordre, "document_id": p.document_id,
        "envoye_le": p.envoye_le.isoformat() if p.envoye_le else None, "notes": p.notes,
        "fournie": bool(p.document_id or p.envoye_le),
    }


def resume_journal(j: FinancementJournal) -> dict[str, Any]:
    return {
        "id": j.id, "financement_id": j.financement_id, "type": j.type, "texte": j.texte,
        "auteur_email": j.auteur_email, "created_at": j.created_at.isoformat() if j.created_at else None,
    }


__all__ = [
    "FINANCEMENT_TYPES", "PARALLELE_TYPE_LABELS", "MAX_PAQUET_BYTES",
    "RentRoll", "rent_roll", "rent_roll_tableau", "rent_roll_pdf", "COLONNES_RENT_ROLL",
    "documents_immeuble", "paquet_pdf", "pieces_defaut", "projection_defaut", "tableau_de_bord",
    "resume_financement", "resume_piece", "resume_journal", "inclusions_de",
]
