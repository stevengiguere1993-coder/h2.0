"""Relevé annuel PDF d'un investisseur (Portail Investisseur v2).

Refonte 2026-08-26 (retour Phil : « le rapport est poche, pas
détaillé, pas de logo ») : en-tête à bande noire avec le logo Horizon,
indicateurs clés, puis UNE SECTION PAR COMPAGNIE — valeur des
immeubles, hypothèques, équité, occupation, vos avances (soldes
QuickBooks par compte) et les mouvements de l'année lus des variations
QuickBooks (visibles même pour un actionnaire sans compte activé).
Généré à la demande — jamais stocké. Aucun TRI (exigence Phil).
"""

from __future__ import annotations

import io
import os
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "logo.png",
)

# Palette du portail (mêmes teintes que l'écran).
_NOIR = "#0f0f0f"
_OR = "#d89b3c"
_OR_FONCE = "#b97e24"
_ENCRE = "#1a1a1a"
_GRIS = "#6b7280"
_GRIS_DOUX = "#9ca3af"
_FOND_DOUX = "#f7f4ee"
_LIGNE = "#e5e7eb"
_VERT = "#047857"
_ROUGE = "#b91c1c"


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} $".replace(",", " ")


def _fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    mois = [
        "janv.", "févr.", "mars", "avr.", "mai", "juin", "juill.",
        "août", "sept.", "oct.", "nov.", "déc.",
    ]
    return f"{d.day} {mois[d.month - 1]} {d.year}"


async def build_releve_pdf(
    db: AsyncSession,
    user: User,
    year: int,
    portefeuille: dict,
    sans_flux: bool = False,
    ident_nom: Optional[str] = None,
    ident_user_id: int = 0,
) -> bytes:
    """``ident_nom`` / ``ident_user_id`` : l'identité de l'actionnaire
    dans les fiches entreprise — sert à retrouver SA ligne d'avances
    (soldes et mouvements QuickBooks) dans chaque compagnie.
    ``sans_flux`` : actionnaire sans compte investisseur — la note des
    mouvements l'explique quand QuickBooks n'a rien à montrer."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as pdfcanvas

    from app.services.invest_portfolio import (
        avances_par_actionnaire,
        entreprise_snapshot,
        partner_directory,
    )

    W, H = letter
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    nom_affiche = ident_nom or (
        f"{user.first_name or ''} {user.last_name or ''}".strip()
        or user.email
    )
    c.setTitle(f"Relevé annuel {year} — {nom_affiche}")
    c.setAuthor("Horizon Services Immobiliers")

    marge = 50
    page_num = [0]

    def txt(x, y, s, size=9, color=_ENCRE, font="Helvetica",
            align="left"):
        c.setFillColor(HexColor(color))
        c.setFont(font, size)
        if align == "right":
            c.drawRightString(x, y, s)
        elif align == "center":
            c.drawCentredString(x, y, s)
        else:
            c.drawString(x, y, s)

    def rrect(x, y, w, h, r, fill, stroke=None, lw=0.8):
        if stroke is not None:
            c.setStrokeColor(HexColor(stroke))
            c.setLineWidth(lw)
        c.setFillColor(HexColor(fill))
        c.roundRect(x, y, w, h, r, stroke=1 if stroke else 0, fill=1)

    def pied():
        page_num[0] += 1
        c.setStrokeColor(HexColor(_LIGNE))
        c.setLineWidth(0.7)
        c.line(marge, 38, W - marge, 38)
        txt(marge, 26,
            f"Relevé annuel {year} · {nom_affiche} · Horizon Services "
            "Immobiliers", 7.5, _GRIS_DOUX)
        txt(W - marge, 26, str(page_num[0]), 8, _GRIS_DOUX,
            align="right")

    def entete(principal: bool) -> float:
        """Bande noire avec logo. Retourne le y de départ du contenu."""
        bh = 96 if principal else 54
        c.setFillColor(HexColor(_NOIR))
        c.rect(0, H - bh, W, bh, stroke=0, fill=1)
        # logo blanc-sur-noir, posé tel quel sur la bande
        try:
            taille = bh - 24
            c.drawImage(
                _LOGO_PATH, marge, H - bh + 12, width=taille,
                height=taille, mask=None,
            )
            lx = marge + taille + 14
        except Exception:  # noqa: BLE001 — sans logo, on écrit quand même
            lx = marge
        if principal:
            txt(lx, H - 42, f"Relevé annuel {year}", 21, "#ffffff",
                "Helvetica-Bold")
            txt(lx, H - 60, nom_affiche, 10.5, _OR, "Helvetica-Bold")
            txt(lx, H - 74,
                f"Préparé le {_fmt_date(date.today().isoformat())} · "
                "Horizon Services Immobiliers", 8, "#bbbbbb")
        else:
            txt(lx, H - 34, f"Relevé annuel {year} — {nom_affiche}",
                11, "#ffffff", "Helvetica-Bold")
        return H - bh - 26

    def nouvelle_page() -> float:
        pied()
        c.showPage()
        return entete(principal=False)

    def besoin(y, h):
        return y - h < 56

    # ── Identité par compagnie (pour retrouver MA ligne d'avances) ──
    async def _ident(entreprise_id: int) -> Optional[str]:
        if ident_nom:
            return ident_nom
        if ident_user_id:
            d = await partner_directory(db, entreprise_id)
            row = d["by_user"].get(ident_user_id)
            return row["name"] if row else None
        return None

    projets = portefeuille.get("projets") or []

    # ═══ Page 1 : sommaire ═══
    y = entete(principal=True)

    # Trois indicateurs clés
    tuiles = [
        ("CAPITAL ACTUELLEMENT INVESTI",
         _money(portefeuille.get("capital_actuel")),
         "solde de vos avances d'actionnaire (QuickBooks)"),
        ("VALEUR DE VOS PARTS",
         _money(portefeuille.get("valeur_parts")),
         "équité des compagnies × vos pourcentages"),
        ("VALEUR TOTALE",
         _money(
             float(portefeuille.get("capital_actuel") or 0)
             + float(portefeuille.get("valeur_parts") or 0)
         ),
         "capital investi + valeur des parts"),
    ]
    tw = (W - 2 * marge - 24) / 3
    for i, (et, val, sous) in enumerate(tuiles):
        x = marge + i * (tw + 12)
        rrect(x, y - 74, tw, 74, 10, _FOND_DOUX)
        txt(x + 12, y - 20, et, 6.4, _GRIS, "Helvetica-Bold")
        txt(x + 12, y - 42, val, 16, _ENCRE, "Helvetica-Bold")
        txt(x + 12, y - 60, sous, 6.4, _GRIS_DOUX)
    y -= 98

    # Tableau des compagnies
    txt(marge, y, "Vos compagnies", 13, _ENCRE, "Helvetica-Bold")
    y -= 20
    cols = [marge, marge + 210, marge + 280, marge + 380,
            W - marge]
    txt(cols[0], y, "COMPAGNIE", 6.6, _GRIS, "Helvetica-Bold")
    txt(cols[1], y, "PART", 6.6, _GRIS, "Helvetica-Bold")
    txt(cols[2] + 70, y, "CAPITAL INVESTI", 6.6, _GRIS,
        "Helvetica-Bold", align="right")
    txt(cols[4], y, "VALEUR DES PARTS", 6.6, _GRIS,
        "Helvetica-Bold", align="right")
    y -= 6
    c.setStrokeColor(HexColor(_LIGNE))
    c.line(marge, y, W - marge, y)
    tot_cap = tot_val = 0.0
    for p in projets:
        y -= 17
        txt(cols[0], y, str(p.get("entreprise_name") or "—"), 9.5,
            _ENCRE)
        txt(cols[1], y, f"{p.get('parts_pct', 0):g} %", 9.5, _ENCRE)
        txt(cols[2] + 70, y, _money(p.get("capital_actuel")), 9.5,
            _ENCRE, align="right")
        txt(cols[4], y, _money(p.get("valeur_parts")), 9.5, _ENCRE,
            align="right")
        tot_cap += float(p.get("capital_actuel") or 0)
        tot_val += float(p.get("valeur_parts") or 0)
    y -= 8
    c.setStrokeColor(HexColor(_LIGNE))
    c.line(marge, y, W - marge, y)
    y -= 16
    txt(cols[0], y, "TOTAL", 9.5, _ENCRE, "Helvetica-Bold")
    txt(cols[2] + 70, y, _money(tot_cap), 9.5, _ENCRE,
        "Helvetica-Bold", align="right")
    txt(cols[4], y, _money(tot_val), 9.5, _ENCRE, "Helvetica-Bold",
        align="right")
    y -= 30

    # ═══ Une section par compagnie ═══
    for p in projets:
        eid = p["entreprise_id"]
        snap = await entreprise_snapshot(db, eid)
        ident = await _ident(eid)
        ma_ligne = None
        av = await avances_par_actionnaire(db, eid)
        if av.get("statut") == "connecte" and ident:
            for a in av.get("actionnaires") or []:
                if a["name"] == ident:
                    ma_ligne = a
                    break

        # hauteur estimée du bloc d'entête de section
        if besoin(y, 150):
            y = nouvelle_page()

        # bandeau de section
        rrect(marge, y - 34, W - 2 * marge, 34, 8, _FOND_DOUX)
        txt(marge + 14, y - 21, str(p.get("entreprise_name") or "—"),
            12, _ENCRE, "Helvetica-Bold")
        txt(W - marge - 14, y - 21,
            f"votre part : {p.get('parts_pct', 0):g} %", 9, _OR_FONCE,
            "Helvetica-Bold", align="right")
        y -= 52

        # chiffres de la compagnie
        paires = [
            ("Valeur des immeubles", _money(snap.get("valeur_totale"))),
            ("Hypothèques", _money(snap.get("hypotheque_totale"))),
            ("Équité de la compagnie", _money(snap.get("equite"))),
            ("Occupation",
             f"{snap.get('nb_baux_actifs', 0)} / "
             f"{snap.get('nb_logements', 0) or '—'} · loyers "
             f"{_money(snap.get('loyers_mensuels'))}/mois"),
            ("Valeur de vos parts", _money(p.get("valeur_parts"))),
        ]
        for et, val in paires:
            txt(marge + 4, y, et, 9, _GRIS)
            txt(W - marge - 4, y, val, 9.5, _ENCRE, "Helvetica-Bold",
                align="right")
            y -= 15
        y -= 4

        # immeubles
        imms = snap.get("immeubles") or []
        if imms:
            if besoin(y, 30 + 14 * len(imms)):
                y = nouvelle_page()
            txt(marge + 4, y, "IMMEUBLES", 6.6, _GRIS,
                "Helvetica-Bold")
            y -= 14
            for im in imms:
                nom_im = str(im.get("address") or im.get("name") or "—")
                txt(marge + 10, y, nom_im[:52], 8.5, _ENCRE)
                txt(W - marge - 4, y,
                    f"valeur {_money(im.get('valeur'))} · hyp. "
                    f"{_money(im.get('hypotheque_balance'))} · équité "
                    f"{_money(im.get('equite'))}", 8, _GRIS,
                    align="right")
                y -= 13
            y -= 6

        # vos avances (soldes QuickBooks)
        if ma_ligne is not None and (ma_ligne.get("comptes") or []):
            comptes = ma_ligne["comptes"]
            if besoin(y, 30 + 14 * len(comptes)):
                y = nouvelle_page()
            txt(marge + 4, y, "VOS AVANCES (SOLDES QUICKBOOKS)", 6.6,
                _GRIS, "Helvetica-Bold")
            y -= 14
            for cpt in comptes:
                txt(marge + 10, y, str(cpt.get("nom") or "—")[:60],
                    8.5, _ENCRE)
                txt(W - marge - 4, y, _money(cpt.get("solde")), 8.5,
                    _ENCRE, "Helvetica-Bold", align="right")
                y -= 13
            # La ligne totale n'apporte rien quand un SEUL compte la
            # porte déjà (retour Phil 2026-08-26 : « pourquoi les 2
            # sont là ? »).
            if len(comptes) > 1:
                txt(marge + 10, y, "Capital encore investi", 8.5,
                    _GRIS)
                solde = ma_ligne.get("solde")
                txt(W - marge - 4, y,
                    "Remboursé complètement" if solde == 0
                    else _money(solde), 8.5,
                    _VERT if solde == 0 else _ENCRE, "Helvetica-Bold",
                    align="right")
                y -= 19
            else:
                y -= 6

        # avances des AUTRES actionnaires de la compagnie (et comptes
        # sans actionnaire correspondant, dûs d'administrateurs
        # compris) — retour Phil 2026-08-26.
        autres_lignes = [
            a
            for a in (av.get("actionnaires") or [])
            if a["name"] != ident and a.get("solde") is not None
        ] if av.get("statut") == "connecte" else []
        autres_cptes = (
            av.get("autres_comptes") or []
            if av.get("statut") == "connecte"
            else []
        )
        if autres_lignes or autres_cptes:
            if besoin(y, 30 + 13 * (len(autres_lignes)
                                    + len(autres_cptes))):
                y = nouvelle_page()
            txt(marge + 4, y, "AVANCES DES AUTRES ACTIONNAIRES", 6.6,
                _GRIS, "Helvetica-Bold")
            y -= 14
            for a in autres_lignes:
                txt(marge + 10, y, str(a["name"])[:60], 8.5, _ENCRE)
                txt(W - marge - 4, y,
                    "Remboursé" if a["solde"] == 0
                    else _money(a["solde"]), 8.5,
                    _VERT if a["solde"] == 0 else _ENCRE,
                    align="right")
                y -= 13
            for cpt in autres_cptes:
                txt(marge + 10, y, str(cpt.get("nom") or "—")[:60],
                    8.5, _GRIS)
                txt(W - marge - 4, y, _money(cpt.get("solde")), 8.5,
                    _GRIS, align="right")
                y -= 13
            if snap.get("avances_actionnaires") is not None:
                txt(marge + 10, y, "Total des avances de la compagnie",
                    8.5, _GRIS)
                txt(W - marge - 4, y,
                    _money(snap.get("avances_actionnaires")), 8.5,
                    _ENCRE, "Helvetica-Bold", align="right")
                y -= 13
            y -= 6

        # mouvements de l'année (variations QuickBooks)
        mvts = [
            m
            for m in (ma_ligne or {}).get("mouvements") or []
            if (m.get("date") or "").startswith(str(year))
            and not m.get("initial")
        ]
        if besoin(y, 30 + 13 * max(1, len(mvts))):
            y = nouvelle_page()
        txt(marge + 4, y, f"VOS MOUVEMENTS DE {year}", 6.6, _GRIS,
            "Helvetica-Bold")
        y -= 14
        if mvts:
            for m in mvts:
                lib = ("Apport de capital" if m["type"] == "apport"
                       else "Remboursement de capital")
                txt(marge + 10, y,
                    f"{_fmt_date(m.get('date'))} — {lib} · "
                    f"{str(m.get('compte') or '')[:44]}", 8.5, _ENCRE)
                signe = "−" if m["type"] == "apport" else "+"
                txt(W - marge - 4, y, f"{signe}{_money(m['montant'])}",
                    8.5,
                    _ROUGE if m["type"] == "apport" else _VERT,
                    "Helvetica-Bold", align="right")
                y -= 13
        else:
            txt(marge + 10, y,
                "Aucun mouvement lisible dans QuickBooks pour cette "
                "période."
                + (" L'historique détaillé apparaîtra après "
                   "l'activation de votre compte."
                   if sans_flux else ""),
                8.5, _GRIS)
            y -= 13
        y -= 22

    # note finale
    if besoin(y, 46):
        y = nouvelle_page()
    c.setStrokeColor(HexColor(_LIGNE))
    c.line(marge, y, W - marge, y)
    y -= 14
    txt(marge, y,
        "Les valeurs de parts reposent sur l'évaluation de référence "
        "des immeubles moins la balance hypothécaire et les avances au",
        7.5, _GRIS_DOUX)
    y -= 11
    txt(marge, y,
        "moment de la génération ; les soldes et mouvements d'avances "
        "sont lus en direct dans QuickBooks. Document informatif — ne",
        7.5, _GRIS_DOUX)
    y -= 11
    txt(marge, y,
        "constitue pas un avis fiscal.", 7.5, _GRIS_DOUX)

    pied()
    c.save()
    return buf.getvalue()
