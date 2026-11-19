"""Abonnements ChantierVrai : offres, prix, periodes, TVA et numerotation des factures.

Logique pure, sans base ni Flask : l'application s'en sert pour facturer ses propres clients
(proprietaires). C'est le chiffre d'affaires de ChantierVrai, pas l'argent des chantiers.
"""
import calendar
from datetime import datetime, timedelta

TRIAL_DAYS = 30          # essai gratuit a l'inscription
GRACE_DAYS = 15          # impaye toléré apres l'echeance avant suspension
ANNUAL_MONTHS = 10       # paiement annuel : 12 mois pour le prix de 10
RENEW_NOTICE_DAYS = 7    # la facture de renouvellement part 7 jours avant l'echeance
REMIND_DAYS = (-3, 3, 10)  # relances : 3 jours avant l'echeance, puis 3 et 10 jours apres

# Prix mensuels par defaut, TTC (le prix que le client paie), modifiables par le super-admin.
# La facture detaille HT et TVA a partir du taux regle dans l'administration.
DEFAULT_VAT = 18           # taux normal en Cote d'Ivoire ; a faire confirmer par le comptable
PLANS = {
    "essai": {"label": "Essai gratuit", "sites": 1, "price": 0,
              "pitch": "30 jours, 1 chantier, toutes les fonctions."},
    "essentiel": {"label": "Essentiel", "sites": 1, "price": 15000,
                  "pitch": "1 chantier suivi : preuves GPS, étapes, paiements suivis, alertes, rapports."},
    "pro": {"label": "Pro", "sites": 5, "price": 45000,
            "pitch": "Jusqu'à 5 chantiers en même temps, équipe et circuit de paiement à deux niveaux."},
    "entreprise": {"label": "Entreprise", "sites": None, "price": None,
                   "pitch": "Chantiers illimités, équipes, API : prix sur devis."},
    "inspection": {"label": "Inspection indépendante", "sites": None, "price": None,
                   "pitch": "Visite d'un inspecteur attribué par ChantierVrai, rapport et photos vérifiées."},
}
INSPECTION_PRICE = 50000   # TTC paye par le client a ChantierVrai
INSPECTION_PAYOUT = 35000  # verse par ChantierVrai a l'inspecteur
PAID_PLANS = ("essentiel", "pro", "entreprise")
# Analyses de qualite par l'IA comprises chaque mois (None = illimite). Les controles par mesures restent illimites.
QUALITY_AI_MONTH = {"essai": 3, "essentiel": 3, "pro": 30, "entreprise": None}
CYCLES = {"mois": "Mensuel", "an": "Annuel (2 mois offerts)"}
SUB_STATUS = {"essai": "Essai gratuit", "essai_fini": "Essai terminé", "actif": "Actif", "impaye": "Paiement en retard",
              "suspendu": "Suspendu (impayé)", "resilie": "Résilié"}
INV_STATUS = {"a_payer": "À payer", "payee": "Payée", "annulee": "Annulée"}
INV_METHODS = {"mobile_money": "Mobile Money ou carte", "virement": "Virement bancaire", "especes": "Espèces",
               "offert": "Offert"}
BLOCKED = ("essai_fini", "suspendu", "resilie")


def monthly_price(plan, prices=None, custom=None):
    """Prix mensuel HT : prix sur mesure du client, sinon prix regle par l'admin, sinon prix par defaut."""
    if custom:
        return int(custom)
    if prices and prices.get(plan) not in (None, ""):
        return int(prices[plan])
    return PLANS[plan]["price"]


def period_price(plan, cycle, prices=None, custom=None):
    m = monthly_price(plan, prices, custom)
    if m is None:
        return None
    return m * (ANNUAL_MONTHS if cycle == "an" else 1)


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def period_end(start, cycle):
    return add_months(start, 12 if cycle == "an" else 1)


def with_vat(amount_ht, rate):
    """(TVA, TTC) arrondis au franc. rate en pourcentage (ex. 18)."""
    vat = round((amount_ht or 0) * (rate or 0) / 100)
    return vat, (amount_ht or 0) + vat


def from_ttc(amount_ttc, rate):
    """(HT, TVA) a partir d'un prix TTC : HT arrondi au franc, TVA = TTC - HT."""
    ht = round((amount_ttc or 0) / (1 + (rate or 0) / 100))
    return ht, (amount_ttc or 0) - ht


def invoice_number(year, seq):
    return f"CV-{year}-{seq:04d}"


def effective_status(sub, now):
    """Statut reel a l'instant : un essai depasse devient « essai termine »."""
    if sub is None:
        return None
    if sub["status"] == "essai" and sub["trial_end"] and datetime.fromisoformat(sub["trial_end"]) <= now:
        return "essai_fini"
    return sub["status"]


def next_status(sub, now, has_open_invoice):
    """Transition quotidienne d'un abonnement payant : actif -> impaye -> suspendu, ou resilie a l'echeance."""
    st = sub["status"]
    if st not in ("actif", "impaye") or not sub["period_end"]:
        return st
    end = datetime.fromisoformat(sub["period_end"])
    if now < end:
        return st
    if sub["cancel_at_end"]:
        return "resilie"
    if not has_open_invoice:
        return st
    return "suspendu" if now >= end + timedelta(days=GRACE_DAYS) else "impaye"


def sites_limit(sub):
    if sub is None:
        return 1
    if sub["sites_limit"]:
        return int(sub["sites_limit"])
    plan = sub["plan"] if sub["plan"] in PLANS else "essai"
    return PLANS[plan]["sites"]
