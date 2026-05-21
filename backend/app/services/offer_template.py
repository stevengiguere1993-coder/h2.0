"""Constantes & templates pour le flow Offre d'achat minimaliste.

On garde tout en dur dans ce fichier : nom de l'acheteur, mentions
légales, helper de mise en lettres du prix, etc. Si Phil veut un jour
rendre tout ça configurable, on déplacera dans une table de
paramètres — pour l'instant, la simplicité prime.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional


# Acheteur par défaut — entité Horizon qui acquiert les immeubles.
# (À déplacer dans Settings si Phil veut éditer plus tard.)
BUYER_ENTITY_NAME = "Horizon Services Immobiliers inc."
BUYER_ENTITY_ADDRESS = "Saint-Hubert (Québec)"

# Mention légale standard insérée en bas du PDF.
LEGAL_NOTICE = (
    "Cette offre d'achat est sous réserve d'une inspection préachat "
    "satisfaisante par un inspecteur certifié, lorsque applicable. "
    "Tous les délais sont calculés en jours civils à partir de la "
    "date d'acceptation par le vendeur. Le présent document constitue "
    "une offre d'achat ferme et irrévocable jusqu'à la date limite "
    "indiquée. La signature électronique a la même valeur juridique "
    "qu'une signature manuscrite en vertu de la Loi concernant le "
    "cadre juridique des technologies de l'information (RLRQ c. C-1.1)."
)


# --- Helpers de formatage ---------------------------------------------


_UNITS = (
    "",
    "un",
    "deux",
    "trois",
    "quatre",
    "cinq",
    "six",
    "sept",
    "huit",
    "neuf",
    "dix",
    "onze",
    "douze",
    "treize",
    "quatorze",
    "quinze",
    "seize",
    "dix-sept",
    "dix-huit",
    "dix-neuf",
)
_TENS = (
    "",
    "",
    "vingt",
    "trente",
    "quarante",
    "cinquante",
    "soixante",
    "soixante",
    "quatre-vingt",
    "quatre-vingt",
)


def _below_100(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    if n < 70:
        t, u = divmod(n, 10)
        if u == 0:
            return _TENS[t]
        if u == 1 and t not in (8,):
            return f"{_TENS[t]}-et-un"
        return f"{_TENS[t]}-{_UNITS[u]}"
    if n < 80:
        return f"soixante-{_below_100(n - 60)}".replace("-", "-").replace(
            "soixante-dix-", "soixante-"
        )
    # 80-99
    if n == 80:
        return "quatre-vingts"
    if n < 100:
        rest = _below_100(n - 80)
        return f"quatre-vingt-{rest}"
    return ""


def _below_1000(n: int) -> str:
    if n < 100:
        return _below_100(n)
    h, rest = divmod(n, 100)
    if h == 1:
        prefix = "cent"
    else:
        prefix = f"{_UNITS[h]} cents" if rest == 0 else f"{_UNITS[h]} cent"
    if rest == 0:
        return prefix
    return f"{prefix} {_below_100(rest)}"


def amount_to_french_words(amount: Optional[float | Decimal]) -> str:
    """Convertit un montant en dollars en mots français (approche
    simple, suffisante jusqu'à quelques millions). Les cents sont
    affichés en chiffres si présents."""
    if amount is None:
        return "—"
    value = Decimal(str(amount))
    cents = int((value % 1) * 100)
    whole = int(value)

    if whole == 0:
        words = "zéro"
    else:
        millions, rest = divmod(whole, 1_000_000)
        thousands, units = divmod(rest, 1_000)
        parts: list[str] = []
        if millions:
            mw = _below_1000(millions)
            parts.append(
                "un million" if millions == 1 else f"{mw} millions"
            )
        if thousands:
            tw = _below_1000(thousands)
            parts.append("mille" if thousands == 1 else f"{tw} mille")
        if units:
            parts.append(_below_1000(units))
        words = " ".join(parts)

    suffix = "dollar" if whole == 1 else "dollars"
    if cents:
        return f"{words} {suffix} et {cents:02d}/100"
    return f"{words} {suffix}"


def format_money(amount: Optional[float | Decimal]) -> str:
    """Format CAD compact : 250 000,00 $"""
    if amount is None:
        return "—"
    s = f"{float(amount):,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} $"
