"""Documents signés AVEC le bail officiel du TAL (Phil 2026-11-13, points 7 et 8).

« Quand on envoie pour la signature du bail, on envoie l'autorisation de communication
électronique. » « Il faut que ça envoie le règlement d'immeuble à signer. »

Ces documents existent déjà dans Kratos : le consentement aux communications électroniques
(texte réglable, Loi concernant le cadre juridique des technologies de l'information) et les
modèles de documents de la gestion locative (règlement d'immeuble, contrat de chambreur… en
texte ou en PDF téléversé). Ce module les joint au bail dans UN SEUL envoi : le locataire
ouvre un lien, signe le bail puis chaque document, à la suite.

Chaque document joint se termine par une page de signature que Kratos génère lui-même, à des
positions connues : c'est là que se posent les zones de signature et de date de chaque
locataire. Le PDF du TAL n'est jamais modifié — il est suivi des documents joints dans
l'enveloppe envoyée en signature ; l'original reste archivé tel quel.
"""

from __future__ import annotations

import io
import logging
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

log = logging.getLogger(__name__)

CLE_CONSENTEMENT = "consentement"
PREFIXE_MODELE = "modele:"

#: Page des documents générés ici : lettre, en points.
LARGEUR, HAUTEUR = 612.0, 792.0
MARGE = 72.0
#: Rangées de signature : une par locataire (le formulaire du bail en prévoit deux).
MAX_SIGNATAIRES = 2


@dataclass
class Annexe:
    cle: str
    titre: str
    pdf: bytes
    #: Zones de la page de signature, numérotées DANS l'annexe (page 1 = sa première page) :
    #: {"page", "rang" (du locataire), "kind", "x", "y", "w", "h"} en fractions de page.
    zones: list[dict[str, Any]] = field(default_factory=list)
    signature: bool = True


def _sans_accents(texte: str) -> str:
    return unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode("ascii").lower()


def est_un_reglement(nom: str) -> bool:
    """Un modèle dont le nom parle de règlement se propose coché (point 8)."""
    return "reglement" in _sans_accents(nom)


# ─── Contexte des modèles, lu dans le formulaire du bail ──────────────


def _date(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _nombre(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def noms_des_locataires(form: dict[str, Any]) -> list[str]:
    return [str(o.get("nom")).strip() for o in (form.get("locataires") or []) if isinstance(o, dict) and str(o.get("nom") or "").strip()]


def contexte(form: dict[str, Any]):
    """Les variables des modèles ({locataire}, {adresse}, {loyer}…) viennent du formulaire du
    bail : même source pour un bail Kratos et pour un bail indépendant."""
    from app.services.tal_forms import TalContext

    f = form if isinstance(form, dict) else {}
    loc = next((o for o in (f.get("locateurs") or []) if isinstance(o, dict)), {})
    adr_loc = next((a for a in (loc.get("adresse") or []) if isinstance(a, dict)), {})
    a = next((o for o in (f.get("adresseLogement") or []) if isinstance(o, dict)), {})
    premier = next((o for o in (f.get("locataires") or []) if isinstance(o, dict)), {})
    indetermine = str(f.get("typeBail") or "") == "dureeIndeterminee"
    return TalContext(
        locateur_nom=str(loc.get("nom") or "").strip() or None,
        locateur_adresse=str(adr_loc.get("AdresseComplete") or "").strip()
        or " ".join(str(adr_loc.get(k) or "").strip() for k in ("NoCivique", "Rue", "Municipalite", "CodePostal")).strip() or None,
        locateur_telephone=str(loc.get("noTelephone") or "").strip() or None,
        locateur_courriel=str(loc.get("courrielLocateur") or loc.get("courrielMandant") or "").strip() or None,
        locataire_nom=", ".join(noms_des_locataires(f)) or None,
        locataire_email=str(premier.get("courrielLocataire") or "").strip() or None,
        logement_adresse=" ".join(str(a.get(k) or "").strip() for k in ("NoCivique", "Rue")).strip() or None,
        logement_numero=str(a.get("Appartement") or "").strip() or None,
        logement_ville=str(a.get("Municipalite") or "").strip() or None,
        bail_date_debut=_date(f.get("dateDebutBailDureeIndeterminee") if indetermine else f.get("dateDebutBail")),
        bail_date_fin=None if indetermine else _date(f.get("dateFinBail")),
        bail_loyer_mensuel=_nombre(f.get("coutTotalLoyer") or f.get("coutLoyer")),
        date_emission=date.today(),
    )


# ─── Pages générées par Kratos (texte + rangées de signature) ─────────


def _page_de_signature(titre: str, paragraphes: list[str], signataires: list[tuple[int, str]]) -> tuple[bytes, list[dict[str, Any]]]:
    """PDF d'une ou plusieurs pages : le titre, le texte, puis une rangée « signature + date »
    par locataire sur la DERNIÈRE page. Retourne (pdf, zones) ; les zones portent le numéro de
    page dans ce PDF et le rang du locataire."""
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LARGEUR, HAUTEUR))
    largeur_texte = LARGEUR - 2 * MARGE
    page = 1

    def entete() -> float:
        c.setFont("Helvetica-Bold", 14)
        y = HAUTEUR - MARGE
        for ligne in simpleSplit(titre, "Helvetica-Bold", 14, largeur_texte):
            c.drawString(MARGE, y, ligne)
            y -= 18
        c.setLineWidth(0.6)
        c.line(MARGE, y + 4, LARGEUR - MARGE, y + 4)
        return y - 16

    y = entete()
    # Hauteur réservée aux signatures en bas de la dernière page.
    reserve = 60 + 78 * max(1, len(signataires))
    for texte in paragraphes:
        texte = (texte or "").replace("**", "").strip()
        if not texte:
            continue
        c.setFont("Helvetica", 10.5)
        for ligne in simpleSplit(texte, "Helvetica", 10.5, largeur_texte):
            if y < MARGE + reserve:
                c.showPage()
                page += 1
                y = entete()
                c.setFont("Helvetica", 10.5)
            c.drawString(MARGE, y, ligne)
            y -= 14.5
        y -= 8

    zones: list[dict[str, Any]] = []
    y = min(y - 18, MARGE + reserve - 30)
    for rang, nom in signataires[:MAX_SIGNATAIRES]:
        ligne_y = y - 34                      # ligne de signature, en points depuis le bas
        c.setLineWidth(0.6)
        c.line(MARGE, ligne_y, MARGE + 280, ligne_y)
        c.line(MARGE + 310, ligne_y, LARGEUR - MARGE, ligne_y)
        c.setFont("Helvetica", 8.5)
        c.drawString(MARGE, ligne_y - 11, f"Signature du locataire — {nom}"[:70])
        c.drawString(MARGE + 310, ligne_y - 11, "Date")
        # Zones : juste au-dessus de la ligne ; origine en haut à gauche, en fractions.
        haut = HAUTEUR - (ligne_y + 34)
        zones.append({"page": page, "rang": rang, "kind": "signature",
                      "x": round((MARGE + 2) / LARGEUR, 6), "y": round(haut / HAUTEUR, 6),
                      "w": round(276 / LARGEUR, 6), "h": round(32 / HAUTEUR, 6)})
        zones.append({"page": page, "rang": rang, "kind": "date",
                      "x": round((MARGE + 312) / LARGEUR, 6), "y": round((HAUTEUR - (ligne_y + 16)) / HAUTEUR, 6),
                      "w": round(150 / LARGEUR, 6), "h": round(14 / HAUTEUR, 6)})
        y -= 78
    c.showPage()
    c.save()
    return buf.getvalue(), zones


def _rendre(texte: str, variables: dict[str, str]) -> str:
    for k, v in variables.items():
        texte = texte.replace("{" + k + "}", v)
    return texte


async def consentement(form: dict[str, Any], signataires: list[tuple[int, str]]) -> Annexe:
    """Consentement aux communications électroniques : le texte réglé dans Kratos (ou le texte
    par défaut), signé par chaque locataire sur la même page."""
    from app.services.tal_forms import GABARITS_DEFAUT, _lettre_variables

    gabarit: Optional[dict] = None
    try:
        from app.api.v1.endpoints.immobilier_extras import _gabarit_override

        gabarit = await _gabarit_override("consentement_communications")
    except Exception:  # noqa: BLE001 — le texte par défaut fait foi
        gabarit = None
    defaut = GABARITS_DEFAUT["consentement_communications"]
    titre = str((gabarit or {}).get("titre") or defaut["titre"])
    paragraphes = [str(p) for p in ((gabarit or {}).get("paragraphes") or defaut["paragraphes"])]
    variables = _lettre_variables("consentement_communications", contexte(form))
    pdf, zones = _page_de_signature(titre, [_rendre(p, variables) for p in paragraphes], signataires)
    return Annexe(cle=CLE_CONSENTEMENT, titre=titre, pdf=pdf, zones=zones)


async def _modele(db: AsyncSession, modele_id: int):
    from app.models.immobilier import ImmDocPersoModele

    return (
        await db.execute(
            select(ImmDocPersoModele).options(undefer(ImmDocPersoModele.pdf_blob)).where(ImmDocPersoModele.id == modele_id)
        )
    ).scalars().first()


async def document_modele(db: AsyncSession, modele_id: int, form: dict[str, Any], signataires: list[tuple[int, str]]) -> Optional[Annexe]:
    """Un modèle de documents (règlement d'immeuble…) : son PDF, suivi d'une page de signature
    si le modèle exige une signature."""
    from pypdf import PdfReader, PdfWriter

    from app.services.tal_bail import TalBailError
    from app.services.tal_forms import generate_perso_pdf

    obj = await _modele(db, modele_id)
    if obj is None:
        return None
    titre = (obj.titre or obj.nom or "Document").strip()
    if obj.pdf_blob:
        corps_pdf = bytes(obj.pdf_blob)
    else:
        paragraphes = [p.strip() for p in (obj.corps or "").replace("\r\n", "\n").split("\n\n")]
        corps_pdf = generate_perso_pdf(titre, paragraphes, contexte(form))
    try:
        nb_pages = len(PdfReader(io.BytesIO(corps_pdf)).pages)
    except Exception as exc:  # noqa: BLE001 — PDF protégé par mot de passe, abîmé…
        nb_pages = 0
        log.warning("Modèle de documents #%s illisible pour l'envoi avec le bail : %s", obj.id, exc)
    if nb_pages < 1:
        raise TalBailError(
            f"Le PDF du modèle « {titre} » est illisible (protégé ou abîmé) : il ne peut pas partir avec le bail. "
            "Téléverse-le de nouveau dans les modèles de documents, ou décoche-le.",
            http_status=422,
        )
    if not obj.signature_requise:
        return Annexe(cle=f"{PREFIXE_MODELE}{obj.id}", titre=titre, pdf=corps_pdf, zones=[], signature=False)
    page_sig, zones = _page_de_signature(
        f"{titre} — signature",
        [f"Je reconnais avoir reçu le document « {titre} », joint à mon bail, en avoir pris connaissance et en accepter les conditions."],
        signataires,
    )
    lecteur = PdfReader(io.BytesIO(corps_pdf))
    w = PdfWriter()
    for p in lecteur.pages:
        w.add_page(p)
    decalage = len(lecteur.pages)
    for p in PdfReader(io.BytesIO(page_sig)).pages:
        w.add_page(p)
    out = io.BytesIO()
    w.write(out)
    return Annexe(cle=f"{PREFIXE_MODELE}{obj.id}", titre=titre, pdf=out.getvalue(),
                  zones=[{**z, "page": z["page"] + decalage} for z in zones])


# ─── Ce qui se propose, ce qui se construit, l'enveloppe ──────────────


async def disponibles(db: AsyncSession) -> list[dict[str, Any]]:
    """Documents qu'on peut joindre au bail pour signature : le consentement aux
    communications électroniques (proposé coché) et les modèles de documents (un règlement se
    propose coché). Jamais bloquant."""
    out: list[dict[str, Any]] = [{
        "cle": CLE_CONSENTEMENT, "titre": "Consentement aux communications électroniques",
        "defaut": True, "signature": True, "source": "Texte réglé dans Kratos",
    }]
    try:
        from app.models.immobilier import ImmDocPersoModele

        modeles = (await db.execute(select(ImmDocPersoModele).order_by(ImmDocPersoModele.nom))).scalars().all()
        for m in modeles:
            out.append({
                "cle": f"{PREFIXE_MODELE}{m.id}", "titre": (m.titre or m.nom or "").strip() or f"Modèle {m.id}",
                "defaut": est_un_reglement(f"{m.nom} {m.titre or ''}"), "signature": bool(m.signature_requise),
                "source": "PDF téléversé" if m.pdf_filename else "Modèle de documents",
            })
    except Exception:  # noqa: BLE001
        log.exception("Modèles de documents illisibles pour les documents joints au bail")
    return out


async def construire(db: AsyncSession, cles: list[str], form: dict[str, Any], signataires: list[tuple[int, str]]) -> list[Annexe]:
    """Les annexes demandées, dans l'ordre demandé. Une clé inconnue est une erreur : on ne
    laisse pas partir un envoi auquel il manquerait un document attendu."""
    from app.services.tal_bail import TalBailError

    annexes: list[Annexe] = []
    vues: set[str] = set()
    for cle in cles or []:
        cle = str(cle or "").strip()
        if not cle or cle in vues:
            continue
        vues.add(cle)
        if cle == CLE_CONSENTEMENT:
            annexes.append(await consentement(form, signataires))
            continue
        if cle.startswith(PREFIXE_MODELE) and cle[len(PREFIXE_MODELE):].isdigit():
            a = await document_modele(db, int(cle[len(PREFIXE_MODELE):]), form, signataires)
            if a is not None:
                annexes.append(a)
                continue
        raise TalBailError(f"Document à joindre introuvable : « {cle} ».", http_status=422)
    return annexes


def assembler(bail_pdf: bytes, annexes: list[Annexe]) -> tuple[bytes, list[dict[str, Any]], list[dict[str, Any]]]:
    """Enveloppe envoyée en signature : le bail du TAL, tel quel, suivi des documents joints.
    Retourne (pdf, zones des annexes avec leur page DANS l'enveloppe, description des annexes)."""
    from pypdf import PdfReader, PdfWriter

    if not annexes:
        return bail_pdf, [], []
    w = PdfWriter()
    n = 0
    for p in PdfReader(io.BytesIO(bail_pdf)).pages:
        w.add_page(p)
        n += 1
    zones: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    for a in annexes:
        pages = PdfReader(io.BytesIO(a.pdf)).pages
        for p in pages:
            w.add_page(p)
        zones.extend({**z, "page": n + z["page"]} for z in a.zones)
        meta.append({"cle": a.cle, "titre": a.titre, "pages": [n + 1, n + len(pages)], "signature": a.signature})
        n += len(pages)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue(), zones, meta


def extraire_pages(pdf: bytes, premiere: int, derniere: int) -> bytes:
    """Les pages ``premiere`` à ``derniere`` (numérotées à partir de 1) d'un PDF."""
    from pypdf import PdfReader, PdfWriter

    lecteur = PdfReader(io.BytesIO(pdf))
    w = PdfWriter()
    for i in range(max(1, premiere), min(len(lecteur.pages), derniere) + 1):
        w.add_page(lecteur.pages[i - 1])
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


__all__ = [
    "CLE_CONSENTEMENT", "PREFIXE_MODELE", "Annexe", "contexte", "noms_des_locataires", "est_un_reglement",
    "consentement", "document_modele", "disponibles", "construire", "assembler", "extraire_pages",
]
