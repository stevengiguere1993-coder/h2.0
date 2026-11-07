"""Portail Investisseur — participations EN CASCADE.

Steven (2026-11-07) : « Vincent détient 30 % dans la compagnie X,
celle-ci détient 50 % d'un projet. Vincent doit voir le projet, la
valeur globale du projet et sa valeur personnelle. »

Une seule source de vérité : « Parts & actionnaires » de la fiche
entreprise (``EntreprisePartner.ownership_pct``).

- Une ligne d'actionnaire PERSONNE (ou personne morale SANS fiche
  Kratos) est une FEUILLE : elle appartient à l'identité qui la porte
  (compte lié, courriel, sinon nom).
- Une ligne d'actionnaire personne morale LIÉE à une de nos fiches
  (``partner_entreprise_id``) est une ARÊTE du graphe : « la compagnie
  H détient q % de la compagnie E ». Elle n'est jamais attribuée
  directement à une personne — ce sont les actionnaires de H qui la
  reçoivent, multipliée.

    % de la personne dans E = Σ sur les chemins (p_H × q_1 × q_2 …)

Service de LECTURE pure ; consommé par le portail (``invest_portal``)
et la console admin (``invest_admin``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.user import User

#: Profondeur maximale d'une chaîne compagnie → compagnie (garde-fou ;
#: une structure réelle dépasse rarement 3).
PROFONDEUR_MAX = 6


def norm_ident(s: Optional[str]) -> str:
    return " ".join((s or "").lower().split())


@dataclass(frozen=True)
class Identite:
    """Qui est « la personne » : compte, courriel et/ou nom affiché.

    Pour un compte connecté : ``user_id`` + ``email`` + ``nom``. Pour
    l'aperçu d'un actionnaire sans compte : ``email`` et/ou ``nom``."""

    user_id: Optional[int] = None
    email: Optional[str] = None
    nom: Optional[str] = None

    @classmethod
    def de_user(cls, u: User) -> "Identite":
        nom = f"{u.first_name or ''} {u.last_name or ''}".strip()
        return cls(
            user_id=u.id,
            email=(u.email or "").strip().lower() or None,
            # Le nom ne sert à l'appariement que s'il est complet
            # (prénom ET nom) — un prénom seul apparierait n'importe qui.
            nom=nom if u.first_name and u.last_name else None,
        )


@dataclass
class Maillon:
    entreprise_id: int
    name: str
    #: % détenu À CE NIVEAU (la personne dans la 1re compagnie, puis
    #: chaque compagnie dans la suivante).
    pct: float


@dataclass
class Chemin:
    #: % effectif de la personne dans le projet par CE chemin.
    pct: float
    #: Du haut vers le bas : [compagnie détenue directement, …, projet].
    maillons: list[Maillon]

    @property
    def direct(self) -> bool:
        return len(self.maillons) == 1

    def to_dict(self) -> dict:
        return {
            "pct": round(self.pct, 3),
            "direct": self.direct,
            "label": " → ".join(
                f"{m.name} ({m.pct:g} %)" for m in self.maillons
            ),
            "maillons": [
                {
                    "entreprise_id": m.entreprise_id,
                    "name": m.name,
                    "pct": round(m.pct, 3),
                }
                for m in self.maillons
            ],
        }


@dataclass
class Detention:
    entreprise_id: int
    name: str
    chemins: list[Chemin] = field(default_factory=list)

    @property
    def pct_total(self) -> float:
        return round(sum(c.pct for c in self.chemins), 3)

    @property
    def pct_direct(self) -> float:
        return round(sum(c.pct for c in self.chemins if c.direct), 3)

    @property
    def pct_indirect(self) -> float:
        return round(sum(c.pct for c in self.chemins if not c.direct), 3)

    def to_dict(self) -> dict:
        return {
            "entreprise_id": self.entreprise_id,
            "name": self.name,
            "pct_total": self.pct_total,
            "pct_direct": self.pct_direct,
            "pct_indirect": self.pct_indirect,
            "chemins": [c.to_dict() for c in self.chemins],
        }


@dataclass
class Graphe:
    """Lignes « Parts & actionnaires » de TOUTES les compagnies actives,
    chargées une fois par requête."""

    #: compagnie → nom
    noms: dict[int, str]
    #: compagnie DÉTENTRICE → [(compagnie détenue, %)]
    detient: dict[int, list[tuple[int, float]]]
    #: compagnie détenue → [(compagnie détentrice, %)]  (sens inverse)
    detenue_par: dict[int, list[tuple[int, float]]]
    #: feuilles : lignes d'actionnaires NON reliées à une fiche
    feuilles: list[EntreprisePartner]
    #: user_id → User (feuilles liées à un compte)
    users: dict[int, User]
    #: courriel (minuscule) → User (feuilles liées par courriel seulement)
    users_par_courriel: dict[str, User]


async def charger_graphe(db: AsyncSession) -> Graphe:
    actives = {
        e.id: e.name
        for e in (
            await db.execute(
                select(Entreprise).where(Entreprise.is_active.is_(True))
            )
        ).scalars()
    }
    detient: dict[int, list[tuple[int, float]]] = {}
    detenue_par: dict[int, list[tuple[int, float]]] = {}
    feuilles: list[EntreprisePartner] = []
    user_ids: set[int] = set()
    for pr in (
        await db.execute(
            select(EntreprisePartner).order_by(EntreprisePartner.id)
        )
    ).scalars():
        if pr.entreprise_id not in actives:
            continue
        pct = float(pr.ownership_pct) if pr.ownership_pct is not None else 0.0
        holding = pr.partner_entreprise_id
        if holding is not None and holding in actives:
            if holding == pr.entreprise_id:
                continue  # une compagnie « se détenant » : ignoré
            detient.setdefault(holding, []).append((pr.entreprise_id, pct))
            detenue_par.setdefault(pr.entreprise_id, []).append(
                (holding, pct)
            )
            continue
        feuilles.append(pr)
        if pr.user_id:
            user_ids.add(pr.user_id)
    users: dict[int, User] = {}
    if user_ids:
        for u in (
            await db.execute(select(User).where(User.id.in_(list(user_ids))))
        ).scalars():
            users[u.id] = u
    # Courriels des feuilles sans compte lié → compte existant au même
    # courriel (c'est ainsi que Vincent, lié par courriel seulement, est
    # reconnu).
    emails = {
        (pr.partner_email or "").strip().lower()
        for pr in feuilles
        if not pr.user_id and pr.partner_email
    }
    emails.discard("")
    users_par_courriel: dict[str, User] = {}
    if emails:
        for u in (
            await db.execute(
                select(User).where(func.lower(User.email).in_(list(emails)))
            )
        ).scalars():
            users_par_courriel[(u.email or "").strip().lower()] = u
    return Graphe(
        noms=actives,
        detient=detient,
        detenue_par=detenue_par,
        feuilles=feuilles,
        users=users,
        users_par_courriel=users_par_courriel,
    )


def _email_feuille(g: Graphe, pr: EntreprisePartner) -> Optional[str]:
    if pr.user_id and pr.user_id in g.users:
        return (g.users[pr.user_id].email or "").strip().lower() or None
    return (pr.partner_email or "").strip().lower() or None


def _user_id_feuille(g: Graphe, pr: EntreprisePartner) -> Optional[int]:
    if pr.user_id:
        return pr.user_id
    email = (pr.partner_email or "").strip().lower()
    u = g.users_par_courriel.get(email) if email else None
    return u.id if u is not None else None


def _nom_feuille(g: Graphe, pr: EntreprisePartner) -> str:
    name = (pr.partner_name or "").strip()
    if name:
        return name
    u = g.users.get(pr.user_id or 0)
    if u is not None:
        return (
            f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email
        )
    return "—"


def feuille_est(g: Graphe, pr: EntreprisePartner, ident: Identite) -> bool:
    """La ligne d'actionnaire ``pr`` désigne-t-elle cette identité ?
    Compte lié, sinon courriel, sinon nom (quand l'identité en a un)."""
    uid = _user_id_feuille(g, pr)
    if ident.user_id is not None and uid == ident.user_id:
        return True
    if ident.email:
        e = _email_feuille(g, pr)
        if e and e == ident.email:
            return True
    if ident.nom and norm_ident(_nom_feuille(g, pr)) == norm_ident(
        ident.nom
    ):
        return True
    return False


def _descendre(
    g: Graphe,
    detentions: dict[int, Detention],
    chemin: list[Maillon],
    pct: float,
) -> None:
    """Depuis la dernière compagnie du chemin, descend dans les
    compagnies qu'elle détient (récursif, borné, sans boucle)."""
    courant = chemin[-1].entreprise_id
    d = detentions.get(courant)
    if d is None:
        d = Detention(courant, g.noms.get(courant, f"#{courant}"))
        detentions[courant] = d
    d.chemins.append(Chemin(pct=pct, maillons=list(chemin)))
    if len(chemin) >= PROFONDEUR_MAX:
        return
    deja = {m.entreprise_id for m in chemin}
    for (cible, q) in g.detient.get(courant, []):
        if cible in deja or q <= 0:
            continue
        _descendre(
            g,
            detentions,
            chemin + [Maillon(cible, g.noms.get(cible, f"#{cible}"), q)],
            pct * q / 100.0,
        )


async def detentions_de(
    db: AsyncSession, ident: Identite, graphe: Optional[Graphe] = None
) -> dict[int, Detention]:
    """Toutes les compagnies où cette identité détient quelque chose,
    directement ou à travers nos compagnies : {entreprise_id: Detention}.
    Les compagnies intermédiaires (holdings) y figurent aussi — à
    l'appelant de distinguer « projet » (immeubles) et « holding »."""
    g = graphe or await charger_graphe(db)
    out: dict[int, Detention] = {}
    vues: set[int] = set()
    for pr in g.feuilles:
        if pr.entreprise_id in vues or not feuille_est(g, pr, ident):
            continue
        # Deux lignes de la même personne sur la même compagnie (ex.
        # courriel ET compte) = une seule part : la première gagne.
        vues.add(pr.entreprise_id)
        p = float(pr.ownership_pct) if pr.ownership_pct is not None else 0.0
        if p <= 0:
            # 0 % (ou vide) : la personne figure quand même à la fiche —
            # on la laisse voir la compagnie, sans valeur.
            d = out.setdefault(
                pr.entreprise_id,
                Detention(
                    pr.entreprise_id, g.noms.get(pr.entreprise_id, "")
                ),
            )
            d.chemins.append(
                Chemin(
                    pct=0.0,
                    maillons=[
                        Maillon(
                            pr.entreprise_id,
                            g.noms.get(pr.entreprise_id, ""),
                            0.0,
                        )
                    ],
                )
            )
            continue
        _descendre(
            g,
            out,
            [Maillon(pr.entreprise_id, g.noms.get(pr.entreprise_id, ""), p)],
            p,
        )
    return out


# ─────────────────────────────────────────────────────────────────────
# Sens inverse : qui, humainement, est derrière un projet ?
# ─────────────────────────────────────────────────────────────────────


@dataclass
class Detenteur:
    """Une personne (ou personne morale feuille) derrière un projet,
    avec son % cumulé et ses chemins."""

    cle: str
    name: str
    email: Optional[str]
    user_id: Optional[int]
    chemins: list[Chemin] = field(default_factory=list)

    @property
    def pct_total(self) -> float:
        return round(sum(c.pct for c in self.chemins), 3)

    def to_dict(self) -> dict:
        return {
            "cle": self.cle,
            "name": self.name,
            "email": self.email,
            "user_id": self.user_id,
            "has_account": self.user_id is not None,
            "pct_total": self.pct_total,
            "pct_direct": round(
                sum(c.pct for c in self.chemins if c.direct), 3
            ),
            "pct_indirect": round(
                sum(c.pct for c in self.chemins if not c.direct), 3
            ),
            "chemins": [c.to_dict() for c in self.chemins],
        }


def _cle_feuille(g: Graphe, pr: EntreprisePartner) -> str:
    uid = _user_id_feuille(g, pr)
    if uid is not None:
        return f"user:{uid}"
    e = _email_feuille(g, pr)
    if e:
        return f"email:{e}"
    return f"nom:{norm_ident(_nom_feuille(g, pr))}"


async def detenteurs_de(
    db: AsyncSession, entreprise_id: int, graphe: Optional[Graphe] = None
) -> list[Detenteur]:
    """Toutes les personnes derrière une compagnie : actionnaires
    directs (feuilles) + actionnaires des compagnies qui la détiennent,
    en remontant les arêtes. Triés par % décroissant."""
    g = graphe or await charger_graphe(db)
    out: dict[str, Detenteur] = {}

    def _remonter(cible: int, suffixe: list[Maillon], facteur: float, deja: set[int]) -> None:
        # Feuilles directes de `cible`.
        for pr in g.feuilles:
            if pr.entreprise_id != cible:
                continue
            p = float(pr.ownership_pct) if pr.ownership_pct is not None else 0.0
            cle = _cle_feuille(g, pr)
            det = out.get(cle)
            if det is None:
                det = Detenteur(
                    cle=cle,
                    name=_nom_feuille(g, pr),
                    email=_email_feuille(g, pr),
                    user_id=_user_id_feuille(g, pr),
                )
                out[cle] = det
            det.chemins.append(
                Chemin(
                    pct=p * facteur,
                    maillons=[Maillon(cible, g.noms.get(cible, ""), p)]
                    + suffixe,
                )
            )
        if len(suffixe) + 1 >= PROFONDEUR_MAX:
            return
        for (holding, q) in g.detenue_par.get(cible, []):
            if holding in deja or q <= 0:
                continue
            _remonter(
                holding,
                [Maillon(cible, g.noms.get(cible, ""), q)] + suffixe,
                facteur * q / 100.0,
                deja | {holding},
            )

    _remonter(entreprise_id, [], 1.0, {entreprise_id})
    dets = list(out.values())
    dets.sort(key=lambda d: (-d.pct_total, d.name.lower()))
    return dets
