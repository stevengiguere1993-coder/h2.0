"""Smoke — les modules de jobs/cron s'importent sans erreur (P-09/P-18).

Contexte : le bug P-18 (un job important un symbole `_public_base` qui
n'existait plus dans `devlog_invoice_send`) est passé sous le radar de la
CI parce que les modules `app.jobs.*` ne sont PAS importés au build de
l'app FastAPI — ils sont chargés paresseusement par le cron runner. Une
`ImportError` ne se manifestait donc qu'au lancement du cron en prod.

Ce filet importe chaque module de `app.jobs` (la surface cron) pour
attraper toute erreur d'import (symbole disparu, import circulaire,
typo) au moment de la CI plutôt qu'en production.
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest

import app.jobs as jobs_pkg

_JOB_MODULES = sorted(
    name for _, name, _ in pkgutil.iter_modules(jobs_pkg.__path__)
)


@pytest.mark.parametrize("module_name", _JOB_MODULES)
def test_job_module_imports(module_name: str) -> None:
    """Chaque `app.jobs.<module>` doit s'importer sans lever."""
    importlib.import_module(f"app.jobs.{module_name}")


def test_at_least_the_known_jobs_present() -> None:
    """Garde-fou : on découvre bien les modules de cron (pas 0)."""
    assert "devlog_facture_reminders" in _JOB_MODULES
    assert len(_JOB_MODULES) >= 10
