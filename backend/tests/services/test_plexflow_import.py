"""Tests du parseur de rent roll PlexFlow (copier-coller).

Couvre les cas réels observés : compagnies multi-immeubles, logements
vacants, baux « scheduled », multi-locataires, numéros tronqués et
étiquettes « Appt # », et la cohérence nb_logements / revenu vs KPI.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.plexflow_import import parse_plexflow


SAMPLE = """9417-1287 Québec Inc.

Shared with you Property
0 67% 3 $880 56
1-3-5 Elgin, Granby (Québec) J2G 4T8
5, Rue Elgin
Granby, J2G 4T8
Unit\tRent\tStatus\tPayment
1-1
Appt # 1
Ghislain Larocque
$600
 Active

 Incomplete
-$2,400
1-3
Appt # 3
-
 Vacant
N/A

Stationne...
Appt # 0
Francois Hivon
$280.56
 Active

 Incomplete
-$1,122.24

Shared with you Property
0 100% 2 $1,150 00
44 kennedy S, Sherbrooke (Québec) J1G 2H6
44, Rue Kennedy Sud
Sherbrooke, J1G 2H6
Unit\tRent\tStatus\tPayment
1
LAKATAN Adebayo Guillaume Wilfried
$150
 Active

 Received
2
Richard Bourrelle, Natacha Bourrelle
$1,000
 Active

 Received
9520-8955 Québec inc,

Shared with you Property
0 50% 2 $1,300 00
9085 Ave Millen, Montréal (Québec) H2M 1W6
9085, Avenue Millen
Montréal, H2M 1W6
Unit\tRent\tStatus\tPayment
1
-
 Vacant
N/A

4
Serena Brynes-Nombres
$1,300
 Scheduled

 Upcoming
"""


def test_parses_companies_and_buildings():
    companies, _ = parse_plexflow(SAMPLE)
    names = [c.name for c in companies]
    # La virgule finale du nom PlexFlow (« inc, ») est nettoyée.
    assert names == ["9417-1287 Québec Inc.", "9520-8955 Québec inc"]
    # 1re compagnie a 2 immeubles, 2e en a 1.
    assert [len(c.buildings) for c in companies] == [2, 1]


def test_addresses_and_unit_counts():
    companies, _ = parse_plexflow(SAMPLE)
    elgin = companies[0].buildings[0]
    assert elgin.address == "5, Rue Elgin"
    assert elgin.city == "Granby"
    assert elgin.postal_code == "J2G 4T8"
    assert elgin.kpi_units == 3
    assert len(elgin.units) == 3  # cohérent avec le KPI
    assert not elgin.warnings


def test_unit_details():
    companies, _ = parse_plexflow(SAMPLE)
    elgin = companies[0].buildings[0]
    by_num = {u.numero: u for u in elgin.units}
    # Locataire + loyer actif
    assert by_num["1-1"].status == "active"
    assert by_num["1-1"].tenant == "Ghislain Larocque"
    assert by_num["1-1"].rent == 600.0
    # Vacant
    assert by_num["1-3"].status == "vacant"
    assert by_num["1-3"].tenant is None
    assert by_num["1-3"].rent is None
    # Numéro tronqué « Stationne... » nettoyé, loyer à décimales
    assert "Stationne" in by_num and by_num["Stationne"].rent == 280.56


def test_multi_tenant_and_scheduled():
    companies, _ = parse_plexflow(SAMPLE)
    kennedy = companies[0].buildings[1]
    multi = {u.numero: u for u in kennedy.units}["2"]
    assert multi.tenant == "Richard Bourrelle, Natacha Bourrelle"

    millen = companies[1].buildings[0]
    sched = {u.numero: u for u in millen.units}["4"]
    assert sched.status == "scheduled"
    assert sched.tenant == "Serena Brynes-Nombres"
    assert sched.rent == 1300.0


def test_revenue_matches_kpi():
    companies, _ = parse_plexflow(SAMPLE)
    elgin = companies[0].buildings[0]
    revenue = sum(u.rent for u in elgin.units if u.rent)
    assert abs(revenue - elgin.kpi_revenue) < 0.01  # 600 + 280.56 = 880.56
