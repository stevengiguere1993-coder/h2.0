"""Téléphonie — heures d'appel personnelles et règles d'acheminement
(bug 19, 2026-10-18) : logique pure, sans base.

Steven : « une personne qui peut être appelée doit pouvoir mettre ses
heures d'appel personnelles » et « plusieurs appelants possibles : un
client appelle pour le projet xyz → ça appelle le responsable du
chantier ».
"""

from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.integrations.voice.call_routing_rules import (
    MAX_STEPS,
    PlannedTarget,
    RoutingPlan,
    build_steps,
    clamp_step_timeout,
    fit_forwarded,
    line_default_field,
    loads_targets,
    normalize_e164,
    normalize_targets,
    select_rule,
)
from app.integrations.voice.routing import _within_windows

MTL = ZoneInfo("America/Montreal")


def _row(dow: int, open_: str, close: str, tz: str = "America/Montreal"):
    oh, om = open_.split(":")
    ch, cm = close.split(":")
    return SimpleNamespace(
        day_of_week=dow,
        open_time=time(int(oh), int(om)),
        close_time=time(int(ch), int(cm)),
        timezone=tz,
    )


# ── Plages horaires ──────────────────────────────────────────────────


def test_aucune_plage_veut_dire_joignable_en_tout_temps():
    assert _within_windows([], datetime(2026, 10, 19, 3, 0, tzinfo=MTL)) is True


def test_dans_la_plage_du_jour():
    lundi_10h = datetime(2026, 10, 19, 10, 0, tzinfo=MTL)  # 2026-10-19 = lundi
    assert _within_windows([_row(0, "08:00", "16:00")], lundi_10h) is True


def test_hors_plage_le_meme_jour_et_autre_jour():
    lundi_19h = datetime(2026, 10, 19, 19, 0, tzinfo=MTL)
    assert _within_windows([_row(0, "08:00", "16:00")], lundi_19h) is False
    mardi_10h = datetime(2026, 10, 20, 10, 0, tzinfo=MTL)
    assert _within_windows([_row(0, "08:00", "16:00")], mardi_10h) is False


def test_plusieurs_plages_le_meme_jour():
    rows = [_row(0, "08:00", "12:00"), _row(0, "13:00", "16:00")]
    assert _within_windows(rows, datetime(2026, 10, 19, 12, 30, tzinfo=MTL)) is False
    assert _within_windows(rows, datetime(2026, 10, 19, 13, 30, tzinfo=MTL)) is True


def test_plage_qui_passe_minuit():
    rows = [_row(0, "22:00", "06:00")]
    assert _within_windows(rows, datetime(2026, 10, 19, 23, 0, tzinfo=MTL)) is True
    assert _within_windows(rows, datetime(2026, 10, 19, 12, 0, tzinfo=MTL)) is False


def test_le_fuseau_de_la_plage_est_respecte():
    # 14 h UTC un lundi = 10 h à Montréal → dans une plage 9 h-12 h locale.
    lundi_14h_utc = datetime(2026, 10, 19, 14, 0, tzinfo=ZoneInfo("UTC"))
    assert _within_windows([_row(0, "09:00", "12:00")], lundi_14h_utc) is True
    # Même instant, plage saisie en heure de Vancouver (7 h locale) → hors plage.
    assert (
        _within_windows([_row(0, "09:00", "12:00", "America/Vancouver")], lundi_14h_utc)
        is False
    )


def test_fuseau_inconnu_retombe_sur_montreal():
    lundi_10h = datetime(2026, 10, 19, 10, 0, tzinfo=MTL)
    assert _within_windows([_row(0, "08:00", "16:00", "Mars/Olympus")], lundi_10h) is True


# ── Cibles d'une règle ───────────────────────────────────────────────


def test_normalisation_des_numeros():
    assert normalize_e164("514 555 0199") == "+15145550199"
    assert normalize_e164("(438) 800-2979") == "+14388002979"
    assert normalize_e164("1 514 555 0199") == "+15145550199"
    assert normalize_e164("+33 1 23 45 67 89") == "+33123456789"
    assert normalize_e164("abc") is None
    assert normalize_e164("") is None
    assert normalize_e164(None) is None


def test_cibles_validees_et_dedoublonnees():
    out = normalize_targets(
        [
            {"kind": "project_responsible"},
            {"kind": "user", "user_id": "5", "label": "  Steven  "},
            {"kind": "e164", "e164": "514-555-0199", "label": "Bureau"},
            {"kind": "user", "user_id": 5},  # doublon → ignoré
            {"kind": "line_default"},
        ]
    )
    assert out == [
        {"kind": "project_responsible"},
        {"kind": "user", "user_id": 5, "label": "Steven"},
        {"kind": "e164", "e164": "+15145550199", "label": "Bureau"},
        {"kind": "line_default"},
    ]


@pytest.mark.parametrize(
    "raw, message",
    [
        ([{"kind": "robot"}], "sorte inconnue"),
        ([{"kind": "user"}], "choisir un utilisateur"),
        ([{"kind": "user", "user_id": "abc"}], "choisir un utilisateur"),
        ([{"kind": "e164", "e164": "12"}], "numéro invalide"),
        (["pas un dict"], "format invalide"),
        ("{pas du json", "illisible"),
        ({"kind": "user"}, "doit être une liste"),
    ],
)
def test_cibles_invalides(raw, message):
    with pytest.raises(ValueError) as exc:
        normalize_targets(raw)
    assert message in str(exc.value)


def test_lecture_tolerante_du_json_stocke():
    assert loads_targets(None) == []
    assert loads_targets("{cassé") == []
    assert loads_targets('{"kind": "user"}') == []
    assert loads_targets('[{"kind": "user", "user_id": 3}, {"kind": "zzz"}, 4]') == [
        {"kind": "user", "user_id": 3}
    ]


def test_delai_par_etape_borne():
    assert clamp_step_timeout(3) == 10
    assert clamp_step_timeout(999) == 45
    assert clamp_step_timeout("20") == 20
    assert clamp_step_timeout(None) == 20


def test_champ_par_defaut_de_la_ligne_selon_le_sujet():
    assert line_default_field("suivi_projet") == "followup_forward_e164"
    assert line_default_field("nouveau_client") == "closer_forward_e164"
    assert line_default_field("urgence_locataire") == "urgency_forward_e164"
    assert line_default_field("demande_locataire") == "urgency_forward_e164"
    assert line_default_field("general") == "forward_to_e164"


# ── Choix de la règle ────────────────────────────────────────────────


def _rule(id_, project_id=None, priority=0, active=True):
    return SimpleNamespace(id=id_, project_id=project_id, priority=priority, active=active)


def test_la_regle_du_chantier_prime_sur_la_regle_generale():
    rules = [_rule(1), _rule(2, project_id=77), _rule(3, project_id=88)]
    assert select_rule(rules, project_id=77).id == 2
    # Appel sans chantier (ou autre chantier) → règle générale seulement.
    assert select_rule(rules, project_id=None).id == 1
    assert select_rule(rules, project_id=99).id == 1


def test_priorite_puis_anciennete_entre_regles_de_meme_portee():
    rules = [_rule(10, priority=0), _rule(11, priority=5), _rule(12, priority=5)]
    assert select_rule(rules, project_id=None).id == 11


def test_regle_inactive_ou_aucune_regle():
    assert select_rule([_rule(1, active=False)], project_id=None) is None
    assert select_rule([], project_id=5) is None
    assert select_rule([_rule(2, project_id=5, active=False), _rule(3)], project_id=5).id == 3


# ── Étapes de sonnerie ───────────────────────────────────────────────


def test_cascade_une_etape_par_cible_dans_l_ordre():
    steps = build_steps([["+15145550001"], ["client:user_2", "+15145550002"], ["+15145550003"]], "cascade")
    assert steps == [["+15145550001"], ["client:user_2", "+15145550002"], ["+15145550003"]]


def test_simultane_tout_le_monde_en_meme_temps():
    steps = build_steps([["+15145550001"], ["+15145550002"], []], "simultane")
    assert steps == [["+15145550001", "+15145550002"]]


def test_une_destination_deja_sonnee_ne_resonne_pas_et_les_vides_sautent():
    steps = build_steps([["+15145550001"], [], ["+15145550001", "+15145550002"], [""]], "cascade")
    assert steps == [["+15145550001"], ["+15145550002"]]


def test_la_cascade_est_plafonnee_sans_perdre_personne():
    groups = [[f"+1514555{i:04d}"] for i in range(MAX_STEPS + 3)]
    steps = build_steps(groups, "cascade")
    assert len(steps) == MAX_STEPS
    assert sum(len(s) for s in steps) == MAX_STEPS + 3
    assert steps[-1] == [g[0] for g in groups[MAX_STEPS - 1 :]]


def test_plan_resolu_saute_les_cibles_marquees():
    plan = RoutingPlan(rule_id=1, mode="cascade", step_timeout_sec=20)
    plan.targets = [
        PlannedTarget(kind="project_responsible", label="Responsable", skipped="hors de ses heures d'appel", destinations=["+15145550001"]),
        PlannedTarget(kind="user", label="Phil", user_id=2, destinations=["client:user_2", "+15145550002"]),
        PlannedTarget(kind="e164", label="Bureau", destinations=["+15145550003"]),
        PlannedTarget(kind="user", label="Zach", user_id=3, skipped="aucun téléphone dans son profil"),
    ]
    assert plan.steps == [["client:user_2", "+15145550002"], ["+15145550003"]]
    assert plan.flat == ["client:user_2", "+15145550002", "+15145550003"]
    assert plan.pstn == ["+15145550002", "+15145550003"]
    d = plan.as_dict()
    assert d["steps"] == plan.steps
    assert [t["skipped"] for t in d["targets"]] == [
        "hors de ses heures d'appel", None, None, "aucun téléphone dans son profil",
    ]


def test_forwarded_to_tient_dans_la_colonne():
    assert fit_forwarded(["+15145550001"]) == "+15145550001"
    # Deux numéros = 25 caractères > 20 → premier numéro seulement.
    assert fit_forwarded(["client:user_2", "+15145550001", "+15145550002"]) == "+15145550001"
    assert fit_forwarded(["client:user_12"]) == "client:user_12"
    assert fit_forwarded([]) is None
