"""Détection de spam sur le formulaire public de contact.

Les bots (spam SEO, gibberish) soumettent des demandes avec des noms
aléatoires (« clkDhFqFhMUfSTCbyyJ »), des courriels Gmail « à points »
(r.i.c.ha.rd.r.o.s.stz.i9.54@gmail.com — Gmail ignore les points, le
spammeur fabrique des adresses uniques) et des messages avec liens.

On NE REJETTE PAS la requête : la demande est créée avec status="spam"
(colonne Spam du CRM, révisable) et TOUS les effets de bord sont sautés
(notification managers, cadence de suivi, accusé de réception, appel
sortant automatique de Léa). Un faux positif se repêche en un clic ;
un bot ne reçoit jamais d'indice qu'il a été détecté.
"""

from __future__ import annotations

import re
from typing import Optional

_VOWELS = set("aeiouyàâäéèêëïîôöùûü")

# Mots-clés typiques du spam SEO / démarchage web dans le message.
_SPAM_KEYWORDS = (
    "seo",
    "backlink",
    "back-link",
    "google ranking",
    "first page of google",
    "page 1 of google",
    "website traffic",
    "web traffic",
    "domain authority",
    "guest post",
    "link building",
    "cryptocurrency",
    "loan offer",
    "viagra",
)

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def _is_gibberish_name(name: str) -> bool:
    """Vrai pour un nom « clavier aléatoire » : un seul mot assez long,
    soit quasi sans voyelles, soit avec des alternances de casse internes
    multiples (aB…cD…eF), ce qu'aucun vrai nom n'a."""
    n = (name or "").strip()
    if not n or " " in n or "-" in n or "'" in n:
        return False
    letters = [c for c in n if c.isalpha()]
    if len(letters) < 8:
        return False
    vowels = sum(1 for c in letters if c.lower() in _VOWELS)
    if vowels / len(letters) < 0.22:
        return True
    # Alternances minuscule→MAJUSCULE à l'intérieur du mot (hors initiale).
    transitions = sum(
        1
        for a, b in zip(n, n[1:])
        if a.isalpha() and b.isalpha() and a.islower() and b.isupper()
    )
    return transitions >= 3


def _is_dotted_gmail(email: str) -> bool:
    """Vrai pour le « dot trick » Gmail : la partie locale est hachée en
    segments d'1-2 caractères par une rafale de points. Gmail ignore les
    points → le spammeur génère des adresses uniques vers la même boîte.
    Un courriel normal (prenom.nom@gmail.com) n'a qu'un point."""
    e = (email or "").strip().lower()
    m = re.match(r"^([^@]+)@(gmail|googlemail)\.com$", e)
    if not m:
        return False
    local = m.group(1)
    dots = local.count(".")
    if dots >= 4:
        return True
    segments = local.split(".")
    short = sum(1 for s in segments if len(s) <= 2)
    return dots >= 2 and short >= 3


def _is_link_spam(message: str) -> bool:
    msg = (message or "").lower()
    if not msg:
        return False
    urls = len(_URL_RE.findall(msg))
    if urls >= 2:
        return True
    has_kw = any(kw in msg for kw in _SPAM_KEYWORDS)
    return has_kw and urls >= 1


def looks_like_spam(
    *,
    name: str,
    email: str,
    message: str,
    honeypot: Optional[str] = None,
) -> Optional[str]:
    """Renvoie la raison (str) si la soumission ressemble à du spam,
    sinon None. Conçu conservateur : un vrai prospect avec un nom normal
    et un courriel normal ne matche aucun signal."""
    if (honeypot or "").strip():
        return "honeypot"
    if _is_gibberish_name(name):
        return "nom_aleatoire"
    if _is_dotted_gmail(email):
        return "gmail_a_points"
    if _is_link_spam(message):
        return "liens_seo"
    return None
