"""Fichier de dépôt direct, norme 005 de Paiements Canada (ex-ACP).

C'est le format que Desjardins attend pour le dépôt direct (DRD) transmis
dans AccèsD Affaires, onglet « Transmission » : enregistrements de 1464
caractères, centre de traitement Desjardins 81510, numéro d'organisme de
10 caractères remis par la caisse.

- « A » : en-tête (organisme, numéro du fichier, date de création,
  centre de traitement, devise) ;
- « C » : crédits (dépôts), jusqu'à 6 segments de 240 caractères par
  enregistrement, un segment par fournisseur payé ;
- « Z » : fin de fichier, nombres et totaux de contrôle.

Champs numériques cadrés à droite et complétés de zéros, champs
alphanumériques cadrés à gauche et complétés d'espaces ; dates au format
« 0AAJJJ » (jour de l'année). Les noms sont mis en majuscules sans
accents : seules les lettres, chiffres, espaces et traits d'union
passent. Un enregistrement par ligne (fin de ligne CR LF).

Le premier fichier d'une entreprise doit être un fichier d'essai validé
par Desjardins avant tout envoi réel.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Sequence

LONGUEUR = 1464
SEGMENT = 240
SEGMENTS_PAR_C = 6
FIN_DE_LIGNE = "\r\n"
#: Centre de traitement de Desjardins (aide-mémoire Transmission de données).
CENTRE_DESJARDINS = "81510"
#: Norme 007 : 460 = comptes fournisseurs (« Accounts Payable »).
CODE_COMPTES_FOURNISSEURS = "460"
MONTANT_MAX_CENTS = 9_999_999_999


class FichierInvalide(ValueError):
    """Donnée qui ne peut pas entrer dans le fichier (message lisible)."""


@dataclass(frozen=True)
class Emetteur:
    numero_organisme: str
    nom_court: str
    nom_long: str
    retour_institution: str
    retour_transit: str
    retour_compte: str
    centre_traitement: str = CENTRE_DESJARDINS
    code_transaction: str = CODE_COMPTES_FOURNISSEURS
    devise: str = "CAD"


@dataclass(frozen=True)
class Depot:
    montant_cents: int
    institution: str
    transit: str
    compte: str
    beneficiaire: str
    #: Référence de l'émetteur (19 car.), pour retrouver le paiement.
    reference: str = ""
    #: Information transmise au fournisseur (15 car.), ex. numéro de facture.
    information: str = ""


# ── Mise en forme des champs ──────────────────────────────────────────


def texte(valeur: str, longueur: int) -> str:
    """Champ alphanumérique : majuscules sans accents, cadré à gauche."""
    base = unicodedata.normalize("NFKD", valeur or "")
    base = "".join(c for c in base if not unicodedata.combining(c)).upper()
    base = re.sub(r"[^A-Z0-9 \-]", " ", base)
    base = re.sub(r" {2,}", " ", base).strip()
    return base[:longueur].ljust(longueur)


def nombre(valeur: int, longueur: int, nom: str) -> str:
    """Champ numérique : cadré à droite, complété de zéros."""
    s = str(int(valeur))
    if int(valeur) < 0 or len(s) > longueur:
        raise FichierInvalide(f"{nom} : « {valeur} » ne tient pas en {longueur} chiffres.")
    return s.zfill(longueur)


def date_julienne(jour: date) -> str:
    """« 0AAJJJ » : 0, deux chiffres de l'année, jour de l'année sur 3."""
    return f"0{jour.year % 100:02d}{jour.timetuple().tm_yday:03d}"


def lire_date_julienne(valeur: str) -> date:
    if len(valeur) != 6 or not valeur.isdigit() or valeur[0] != "0":
        raise FichierInvalide(f"Date « {valeur} » invalide (format 0AAJJJ).")
    return datetime.strptime(f"20{valeur[1:3]}{valeur[3:]}", "%Y%j").date()


def _chiffres(valeur: str, longueur: int, nom: str) -> str:
    v = (valeur or "").strip()
    if not v.isdigit() or len(v) != longueur:
        raise FichierInvalide(f"{nom} : {longueur} chiffres attendus.")
    return v


def _compte(valeur: str, nom: str) -> str:
    v = (valeur or "").strip()
    if not v.isdigit() or not 1 <= len(v) <= 12:
        raise FichierInvalide(f"{nom} : de 1 à 12 chiffres attendus.")
    return v.ljust(12)


def _organisme(valeur: str) -> str:
    v = (valeur or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{10}", v):
        raise FichierInvalide("Numéro d'organisme : 10 caractères attendus.")
    return v


def institution_9(institution: str, transit: str, nom: str) -> str:
    """Numéro d'identification de l'institution : 0 + institution + transit."""
    return "0" + _chiffres(institution, 3, f"{nom} (institution)") + _chiffres(
        transit, 5, f"{nom} (transit)"
    )


# ── Création ──────────────────────────────────────────────────────────


def _segment(emetteur: Emetteur, depot: Depot, date_depot: date) -> str:
    if not 0 < int(depot.montant_cents) <= MONTANT_MAX_CENTS:
        raise FichierInvalide(f"Montant invalide pour {depot.beneficiaire or 'un fournisseur'}.")
    if not texte(depot.beneficiaire, 30).strip():
        raise FichierInvalide("Nom du fournisseur manquant.")
    seg = "".join(
        [
            _chiffres(emetteur.code_transaction, 3, "Code de transaction"),
            nombre(depot.montant_cents, 10, "Montant"),
            date_julienne(date_depot),
            institution_9(depot.institution, depot.transit, depot.beneficiaire),
            _compte(depot.compte, f"Compte de {depot.beneficiaire}"),
            "0" * 22,  # numéro de trace : attribué par l'institution
            "000",  # type de transaction mémorisé : zéros à l'envoi
            texte(emetteur.nom_court, 15),
            texte(depot.beneficiaire, 30),
            texte(emetteur.nom_long, 30),
            texte(emetteur.numero_organisme, 10),
            texte(depot.reference, 19),
            institution_9(emetteur.retour_institution, emetteur.retour_transit, "Compte de retour"),
            _compte(emetteur.retour_compte, "Compte de retour"),
            texte(depot.information, 15),
            " " * 22,
            "  ",  # code de règlement : réservé aux institutions
            "0" * 11,  # éléments invalides : zéros à l'envoi
        ]
    )
    assert len(seg) == SEGMENT, len(seg)
    return seg


def generer(
    emetteur: Emetteur,
    depots: Sequence[Depot],
    *,
    numero_fichier: int,
    date_creation: date,
    date_depot: date,
) -> str:
    """Contenu complet du fichier (texte ASCII, une ligne par enregistrement)."""
    organisme = _organisme(emetteur.numero_organisme)
    if not 1 <= int(numero_fichier) <= 9999:
        raise FichierInvalide("Numéro de fichier : de 0001 à 9999.")
    centre = _chiffres(emetteur.centre_traitement, 5, "Centre de traitement")
    devise = (emetteur.devise or "").upper()
    if devise not in ("CAD", "USD"):
        raise FichierInvalide("Devise : CAD ou USD.")
    if not texte(emetteur.nom_court, 15).strip() or not texte(emetteur.nom_long, 30).strip():
        raise FichierInvalide("Nom court et nom long de l'entreprise requis.")
    if not depots:
        raise FichierInvalide("Aucun dépôt dans le fichier.")
    controle = organisme + nombre(numero_fichier, 4, "Numéro de fichier")

    enregistrements: List[str] = []
    compteur = 1
    enregistrements.append(
        "A"
        + nombre(compteur, 9, "Compteur")
        + controle
        + date_julienne(date_creation)
        + centre
        + " " * 20
        + devise
    )
    segments = [_segment(emetteur, d, date_depot) for d in depots]
    for i in range(0, len(segments), SEGMENTS_PAR_C):
        compteur += 1
        lot = segments[i : i + SEGMENTS_PAR_C]
        lot += [" " * SEGMENT] * (SEGMENTS_PAR_C - len(lot))
        enregistrements.append("C" + nombre(compteur, 9, "Compteur") + controle + "".join(lot))
    compteur += 1
    total = sum(int(d.montant_cents) for d in depots)
    enregistrements.append(
        "Z"
        + nombre(compteur, 9, "Compteur")
        + controle
        + "0" * 14
        + "0" * 8
        + nombre(total, 14, "Total des crédits")
        + nombre(len(depots), 8, "Nombre de crédits")
        + "0" * 44
    )
    lignes = [e.ljust(LONGUEUR) for e in enregistrements]
    assert all(len(ligne) == LONGUEUR for ligne in lignes)
    return FIN_DE_LIGNE.join(lignes) + FIN_DE_LIGNE


# ── Relecture (aperçu et contrôle) ────────────────────────────────────


def lire(contenu: str) -> Dict[str, Any]:
    """Relit un fichier et en vérifie la structure et les totaux.

    Sert d'aperçu avant la transmission (ce que Desjardins lira) et de
    garde-fou : un fichier mal formé ne sort pas de Kratos.
    """
    lignes = [ligne for ligne in contenu.split(FIN_DE_LIGNE) if ligne]
    if len(lignes) < 3:
        raise FichierInvalide("Fichier incomplet.")
    for n, ligne in enumerate(lignes, start=1):
        if len(ligne) != LONGUEUR:
            raise FichierInvalide(f"Enregistrement {n} : {len(ligne)} caractères au lieu de {LONGUEUR}.")
        if int(ligne[1:10]) != n:
            raise FichierInvalide(f"Enregistrement {n} : compteur {ligne[1:10]}.")
    tete, fin = lignes[0], lignes[-1]
    if tete[0] != "A" or fin[0] != "Z":
        raise FichierInvalide("Le fichier doit commencer par « A » et finir par « Z ».")
    controle = tete[10:24]
    depots: List[Dict[str, Any]] = []
    for ligne in lignes[1:-1]:
        if ligne[0] != "C" or ligne[10:24] != controle:
            raise FichierInvalide("Enregistrement de dépôt invalide.")
        for k in range(SEGMENTS_PAR_C):
            seg = ligne[24 + k * SEGMENT : 24 + (k + 1) * SEGMENT]
            if not seg.strip():
                continue
            depots.append(
                {
                    "code_transaction": seg[0:3],
                    "montant_cents": int(seg[3:13]),
                    "date_depot": lire_date_julienne(seg[13:19]).isoformat(),
                    "institution": seg[20:23],
                    "transit": seg[23:28],
                    "compte": seg[28:40].strip(),
                    "nom_court": seg[65:80].strip(),
                    "beneficiaire": seg[80:110].strip(),
                    "nom_long": seg[110:140].strip(),
                    "reference": seg[150:169].strip(),
                    "retour_institution": seg[170:173],
                    "retour_transit": seg[173:178],
                    "retour_compte": seg[178:190].strip(),
                    "information": seg[190:205].strip(),
                }
            )
    if fin[10:24] != controle:
        raise FichierInvalide("Fin de fichier : données de contrôle différentes de l'en-tête.")
    total = int(fin[46:60])
    nombre_credits = int(fin[60:68])
    if total != sum(d["montant_cents"] for d in depots) or nombre_credits != len(depots):
        raise FichierInvalide("Fin de fichier : totaux de contrôle faux.")
    return {
        "numero_organisme": tete[10:20],
        "numero_fichier": int(tete[20:24]),
        "date_creation": lire_date_julienne(tete[24:30]).isoformat(),
        "centre_traitement": tete[30:35],
        "devise": tete[55:58],
        "depots": depots,
        "nombre": nombre_credits,
        "total_cents": total,
    }
