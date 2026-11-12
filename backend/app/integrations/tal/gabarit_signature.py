"""Où se signe le bail officiel du TAL (formulaire 53000BAIL) — gabarit des zones.

Phil 2026-11-11 : « que ça vienne mettre au bon endroit toutes les initiales, toutes
les signatures demandées, sans qu'on ait à le remplir à chaque fois ».

Le PDF du TAL revient verrouillé, toujours au même gabarit : pages 612 × 1008 points,
quatre pages de formulaire puis les mentions. Les positions ci-dessous ont été relevées
sur le premier bail réel (2026-11-11) et sur le bail d'essai fourni par le TAL :
identiques au point près. Elles sont exprimées en points, origine en haut à gauche.

Kratos ne pose JAMAIS une signature à l'aveugle. Avant de poser les zones,
``verifier_gabarit`` relit le PDF et compare son empreinte : taille des pages, nombre de
cases d'initiales et de lignes de signature par page. Si le TAL change son formulaire,
l'empreinte ne correspond plus et l'envoi automatique se refuse, au lieu de faire signer
au mauvais endroit. Le gabarit vaut pour le bail en français sans Annexe 6.

Le formulaire n'a que deux lignes de signature par partie (deux locateurs, deux
locataires, deux autres signataires) : au-delà, pas de signature en ligne automatique.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

LARGEUR = 612.0
HAUTEUR = 1008.0
#: Pages du formulaire qui portent des zones.
PAGES_FORMULAIRE = 4
#: Lignes de signature offertes par le formulaire, par partie.
MAX_PAR_PARTIE = 2

PARTIES = ("locateur", "locataire", "autre")

LIB_INIT_LOCATEUR = "Initiales du locateur"
LIB_INIT_LOCATAIRE = "Initiales du locataire"
LIB_SIG_LOCATEUR = "Signature du locateur"
LIB_SIG_LOCATAIRE = "Signature du locataire"
LIB_SIG_CONJOINT = "Signature du locataire ou du conjoint du locataire"
LIB_SIG_AUTRE = "Signature"
LIB_DATE = "Jour Mois Année"

#: Libellés comptés pour l'empreinte (page → libellé → nombre d'occurrences).
LIBELLES_EMPREINTE = (LIB_INIT_LOCATEUR, LIB_INIT_LOCATAIRE, LIB_SIG_LOCATEUR, LIB_SIG_LOCATAIRE)
#: Relevé sur le bail réel et sur le bail d'essai du TAL (pypdf). « Signature du locataire »
#: vaut 5 en page 4 : deux à l'avis (G), deux aux signatures (H), une à l'avis de résidence
#: familiale (I).
EMPREINTE: dict[int, dict[str, int]] = {
    1: {LIB_INIT_LOCATEUR: 4, LIB_INIT_LOCATAIRE: 4, LIB_SIG_LOCATEUR: 0, LIB_SIG_LOCATAIRE: 0},
    2: {LIB_INIT_LOCATEUR: 2, LIB_INIT_LOCATAIRE: 8, LIB_SIG_LOCATEUR: 0, LIB_SIG_LOCATAIRE: 0},
    3: {LIB_INIT_LOCATEUR: 2, LIB_INIT_LOCATAIRE: 2, LIB_SIG_LOCATEUR: 0, LIB_SIG_LOCATAIRE: 0},
    4: {LIB_INIT_LOCATEUR: 2, LIB_INIT_LOCATAIRE: 4, LIB_SIG_LOCATEUR: 4, LIB_SIG_LOCATAIRE: 5},
}
#: Une page au-delà du formulaire qui porte ces mots a des cases que ce gabarit ne connaît pas (Annexe 6).
_MARQUES_HORS_GABARIT = ("Initiales du locat", "Signature du locat")


@dataclass(frozen=True)
class Zone:
    """Une zone du gabarit. ``rang`` : rang de la personne dans sa partie (1 ou 2) ;
    0 = la première personne de la partie qui signe en ligne (date commune à la partie,
    ou personne désignée par le formulaire)."""

    cle: str        # pied | fumee | cheques | reglement | copropriete | avis | signatures | solidaire | autre | famille
    page: int
    partie: str     # locateur | locataire | autre
    rang: int
    kind: str       # signature | initiales | date
    x: float
    y: float
    w: float
    h: float
    libelle: str    # libellé imprimé sous la ligne

    @property
    def ligne_y(self) -> float:
        """Hauteur de la ligne du formulaire sous la zone (le libellé est juste dessous)."""
        return self.y + self.h + 2.0


def _initiales(cle: str, page: int, partie: str, rang: int, x0: float, x1: float, ligne: float) -> Zone:
    lib = LIB_INIT_LOCATEUR if partie == "locateur" else LIB_INIT_LOCATAIRE
    return Zone(cle, page, partie, rang, "initiales", x0 + 2, ligne - 18, (x1 - x0) - 4, 16, lib)


def _signature(cle: str, page: int, partie: str, rang: int, x0: float, x1: float, ligne: float, *, h: float = 16, libelle: str = "") -> Zone:
    lib = libelle or (LIB_SIG_LOCATEUR if partie == "locateur" else LIB_SIG_LOCATAIRE if partie == "locataire" else LIB_SIG_AUTRE)
    return Zone(cle, page, partie, rang, "signature", x0 + 2, ligne - h - 2, (x1 - x0) - 4, h, lib)


def _date(cle: str, page: int, partie: str, rang: int, x_jour: float, y_libelle: float) -> Zone:
    """Les trois cases « Jour Mois Année » sont juste au-dessus de leur libellé."""
    return Zone(cle, page, partie, rang, "date", x_jour - 3, y_libelle - 14, 80, 12, LIB_DATE)


def _construire() -> tuple[Zone, ...]:
    z: list[Zone] = []
    # Pied de chaque page du formulaire : initiales des deux locateurs et des deux locataires.
    for page in range(1, PAGES_FORMULAIRE + 1):
        z.append(_initiales("pied", page, "locateur", 1, 234, 315, 980))
        z.append(_initiales("pied", page, "locateur", 2, 324, 405, 980))
        z.append(_initiales("pied", page, "locataire", 1, 414, 495, 980))
        z.append(_initiales("pied", page, "locataire", 2, 504, 585, 980))
    # Page 1 — engagement sur les avertisseurs de fumée.
    z.append(_initiales("fumee", 1, "locateur", 1, 46, 109, 913))
    z.append(_initiales("fumee", 1, "locateur", 2, 118, 181, 913))
    z.append(_date("fumee", 1, "locateur", 0, 202, 914))
    z.append(_initiales("fumee", 1, "locataire", 1, 335, 399, 913))
    z.append(_initiales("fumee", 1, "locataire", 2, 404, 471, 913))
    z.append(_date("fumee", 1, "locataire", 0, 496, 914))
    # Page 2 — initiales du locataire : chèques postdatés, règlement de l'immeuble, copropriété divise.
    z.append(_initiales("cheques", 2, "locataire", 1, 103, 198, 486))
    z.append(_initiales("cheques", 2, "locataire", 2, 207, 303, 486))
    for cle, ligne in (("reglement", 608), ("copropriete", 672)):
        z.append(_initiales(cle, 2, "locataire", 1, 176, 272, ligne))
        z.append(_initiales(cle, 2, "locataire", 2, 280, 376, ligne))
    # Page 4 — avis au nouveau locataire (G) : deux rangées, locateur à gauche, locataire à droite.
    for rang, (ligne, y_lib) in enumerate(((180, 180), (206, 207)), 1):
        z.append(_signature("avis", 4, "locateur", rang, 36, 206, ligne, h=15))
        z.append(_date("avis", 4, "locateur", rang, 215, y_lib))
        z.append(_signature("avis", 4, "locataire", rang, 316, 486, ligne, h=15))
        z.append(_date("avis", 4, "locataire", rang, 495, y_lib))
    # Page 4 — signatures (H) : deux rangées.
    for rang, (ligne, y_lib) in enumerate(((261, 261), (291, 292)), 1):
        z.append(_signature("signatures", 4, "locateur", rang, 36, 206, ligne))
        z.append(_date("signatures", 4, "locateur", rang, 215, y_lib))
        z.append(_signature("signatures", 4, "locataire", rang, 300, 470, ligne))
        z.append(_date("signatures", 4, "locataire", rang, 479, y_lib))
    # Page 4 — engagement solidaire des locataires.
    z.append(_initiales("solidaire", 4, "locataire", 1, 347, 412, 326))
    z.append(_initiales("solidaire", 4, "locataire", 2, 421, 487, 326))
    # Page 4 — autres signataires (cautions) : le nom, la qualité et l'adresse sont imprimés par le TAL.
    for rang, (ligne, y_lib) in enumerate(((378, 406), (440, 468)), 1):
        z.append(_signature("autre", 4, "autre", rang, 198, 440, ligne))
        z.append(_date("autre", 4, "autre", rang, 494, y_lib))
    # Page 4 — avis de résidence familiale (I) : une seule ligne, pour le locataire qui donne l'avis.
    z.append(_signature("famille", 4, "locataire", 0, 36, 234, 660, h=13, libelle=LIB_SIG_CONJOINT))
    z.append(_date("famille", 4, "locataire", 0, 242, 661))
    return tuple(z)


GABARIT: tuple[Zone, ...] = _construire()


def empreinte_du_gabarit() -> dict[int, dict[str, int]]:
    """Ce que le gabarit prévoit, compté comme ``verifier_gabarit`` compte le PDF (test de cohérence)."""
    out = {p: {lib: 0 for lib in LIBELLES_EMPREINTE} for p in range(1, PAGES_FORMULAIRE + 1)}
    for zone in GABARIT:
        for lib in LIBELLES_EMPREINTE:
            if lib in zone.libelle:
                out[zone.page][lib] += 1
    return out


# ─── Vérification du PDF reçu ─────────────────────────────────────────


@dataclass(frozen=True)
class Verdict:
    ok: bool
    motif: Optional[str] = None
    pages: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "motif": self.motif, "pages": self.pages}


def _texte(page: Any) -> str:
    return re.sub(r"\s+", " ", page.extract_text() or "")


def _proche(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= 0.75


def verifier_gabarit(pdf: bytes) -> Verdict:
    """Le PDF est-il bien le bail officiel au gabarit connu ? Ne lève jamais."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf))
        nb = len(reader.pages)
    except Exception:  # noqa: BLE001
        return Verdict(False, "le PDF du bail est illisible")
    if nb < PAGES_FORMULAIRE:
        return Verdict(False, f"le PDF compte {nb} page(s) au lieu des {PAGES_FORMULAIRE} pages du formulaire", nb)
    try:
        for no in range(1, nb + 1):
            page = reader.pages[no - 1]
            texte = _texte(page)
            if no > PAGES_FORMULAIRE:
                if any(m in texte for m in _MARQUES_HORS_GABARIT):
                    return Verdict(False, f"la page {no} porte des cases de signature que Kratos ne connaît pas (annexe au bail)", nb)
                continue
            mb, cb = page.mediabox, page.cropbox
            dimensions_ok = (
                _proche(mb.width, LARGEUR) and _proche(mb.height, HAUTEUR) and _proche(mb.left, 0) and _proche(mb.bottom, 0)
                and _proche(cb.left, mb.left) and _proche(cb.bottom, mb.bottom) and _proche(cb.right, mb.right) and _proche(cb.top, mb.top)
            )
            if not dimensions_ok or int(getattr(page, "rotation", 0) or 0) % 360 != 0:
                return Verdict(False, f"la page {no} n'a pas le format du formulaire officiel", nb)
            comptes = {lib: texte.count(lib) for lib in LIBELLES_EMPREINTE}
            if comptes != EMPREINTE[no]:
                ecarts = ", ".join(f"« {lib} » {comptes[lib]} au lieu de {EMPREINTE[no][lib]}" for lib in LIBELLES_EMPREINTE if comptes[lib] != EMPREINTE[no][lib])
                return Verdict(False, f"la page {no} ne correspond pas au formulaire connu ({ecarts})", nb)
    except Exception:  # noqa: BLE001
        return Verdict(False, "le PDF du bail n'a pas pu être analysé", nb)
    return Verdict(True, None, nb)


# ─── Zones à poser pour un bail donné ─────────────────────────────────


def _oui(v: Any) -> bool:
    """Réponse « oui » d'un bouton radio (« true ») ou d'une case cochée (booléen ou liste)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (list, tuple)):
        return any(x is True or (isinstance(x, str) and x.strip().lower() not in ("", "false")) for x in v)
    return str(v or "").strip().lower() == "true"


def _nb_nommes(form: dict[str, Any], groupe: str) -> int:
    return sum(1 for occ in (form.get(groupe) or []) if isinstance(occ, dict) and str(occ.get("nom") or "").strip())


def rang_avis_residence_familiale(form: dict[str, Any]) -> int:
    """Rang du locataire qui donne l'avis de résidence familiale (section I), 0 si aucun."""
    for rang in range(1, MAX_PAR_PARTIE + 1):
        if _oui(form.get(f"locataire{rang}logementResidenceFamiliale")):
            return rang
    return 0


def sections_applicables(form: dict[str, Any]) -> set[str]:
    """Les parties du formulaire qui demandent des initiales ou une signature pour CE bail.
    Les engagements facultatifs (chèques postdatés, règlement remis, solidarité, résidence
    familiale) ne sont paraphés que s'ils sont pris."""
    cles = {"pied", "fumee", "avis", "signatures", "autre"}
    if _oui(form.get("locataireAccepteRemiseChequePostdates")):
        cles.add("cheques")
    if _oui(form.get("possedeRemiseReglementImmeuble")):
        cles.add("reglement")
    if _oui(form.get("logementCoproprieteDivise")) and _oui(form.get("possedeRemiseReglementImmeubleCoproprieteDivise")):
        cles.add("copropriete")
    if _oui(form.get("estLocatairesEngagementSolidaire")) and _nb_nommes(form, "locataires") >= 2:
        cles.add("solidaire")
    if rang_avis_residence_familiale(form):
        cles.add("famille")
    return cles


def zones_a_poser(form: dict[str, Any], presents: Iterable[tuple[str, int]]) -> list[Zone]:
    """Zones du gabarit pour ce bail, limitées aux personnes qui signent en ligne.

    ``presents`` : couples (partie, rang) des signataires invités. Une personne absente
    (pas de courriel) laisse ses cases libres pour une signature à la main. Chaque zone
    retournée porte le rang réel de son signataire.
    """
    ici = {(str(p), int(r)) for p, r in presents}
    cles = sections_applicables(form)
    premier = {partie: min((r for p, r in ici if p == partie), default=0) for partie in PARTIES}
    famille = rang_avis_residence_familiale(form)
    out: list[Zone] = []
    for zone in GABARIT:
        if zone.cle not in cles:
            continue
        rang = zone.rang
        if rang == 0:
            rang = famille if zone.cle == "famille" else premier[zone.partie]
        if not rang or (zone.partie, rang) not in ici:
            continue
        out.append(zone if rang == zone.rang else Zone(zone.cle, zone.page, zone.partie, rang, zone.kind, zone.x, zone.y, zone.w, zone.h, zone.libelle))
    return out


def fractions(zone: Zone) -> dict[str, float]:
    """Position de la zone en fractions de page (ce qu'attend l'outil de signature)."""
    return {
        "x": round(zone.x / LARGEUR, 6), "y": round(zone.y / HAUTEUR, 6),
        "w": round(zone.w / LARGEUR, 6), "h": round(zone.h / HAUTEUR, 6),
    }


__all__ = [
    "LARGEUR", "HAUTEUR", "PAGES_FORMULAIRE", "MAX_PAR_PARTIE", "PARTIES", "GABARIT", "EMPREINTE", "LIBELLES_EMPREINTE",
    "LIB_DATE", "Zone", "Verdict", "empreinte_du_gabarit", "verifier_gabarit", "sections_applicables",
    "rang_avis_residence_familiale", "zones_a_poser", "fractions",
]
