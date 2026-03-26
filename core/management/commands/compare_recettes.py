"""
Script de diagnostic : compare les colis comptabilisés dans le Dashboard
vs le Rapport Financier Avancé pour un mois/année donnés.

Utilisation :
    poetry run python manage.py compare_recettes
    poetry run python manage.py compare_recettes --month 3 --year 2026
    poetry run python manage.py compare_recettes --month 3 --year 2026 --destination 2
"""

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum, Case, When, Value, F, DecimalField
from core.models import Colis, Country
from django.utils import timezone


def get_net(c):
    """Calcule le montant net encaissé pour un colis."""
    if c.paye_en_chine:
        return 0
    return float(c.prix_final or 0) - float(c.montant_jc or 0) - float(c.reste_a_payer or 0)


class Command(BaseCommand):
    help = "Compare les colis comptabilisés dans le Dashboard vs le Rapport Avancé."

    def add_arguments(self, parser):
        now = timezone.now()
        parser.add_argument("--month", type=int, default=now.month)
        parser.add_argument("--year", type=int, default=now.year)
        parser.add_argument("--destination", type=int, default=None,
                            help="ID du pays (ex: 2 pour Mali). Optionnel.")

    def handle(self, *args, **options):
        month = options["month"]
        year = options["year"]
        dest_id = options["destination"]

        self.stdout.write(
            self.style.HTTP_INFO(f"\n══════════════════════════════════════════════")
        )
        self.stdout.write(
            self.style.HTTP_INFO(f"  DIAGNOSTIC RECETTES — {month:02d}/{year}")
        )
        self.stdout.write(
            self.style.HTTP_INFO(f"══════════════════════════════════════════════\n")
        )

        base_qs = Colis.objects.filter(status="LIVRE")
        if dest_id:
            base_qs = base_qs.filter(lot__destination_id=dest_id)
            try:
                dest_name = Country.objects.get(pk=dest_id).name
            except Country.DoesNotExist:
                dest_name = f"ID={dest_id}"
            self.stdout.write(f"  Destination filtrée : {dest_name}\n")

        # --- DASHBOARD AGENT MALI ---
        # Nouvelle formule (date_livraison ou date_encaissement)
        qs_dashboard = base_qs.filter(
            Q(date_encaissement__year=year, date_encaissement__month=month) |
            Q(date_encaissement__isnull=True, date_livraison__year=year, date_livraison__month=month)
        )
        ids_dashboard = set(qs_dashboard.values_list("id", flat=True))

        # --- ANCIEN DASHBOARD (updated_at) pour comparaison diagnostic ---
        from django.utils import timezone
        first_day = timezone.datetime(year, month, 1).date()
        qs_old_dashboard = base_qs.filter(updated_at__date__gte=first_day,
                                          updated_at__year=year, updated_at__month=month)
        ids_old_dashboard = set(qs_old_dashboard.values_list("id", flat=True))

        # --- RAPPORT AVANCÉ ---
        # Même filtre (après notre correction, ils doivent être identiques)
        qs_rapport = base_qs.filter(
            Q(date_encaissement__year=year, date_encaissement__month=month) |
            Q(date_encaissement__isnull=True, date_livraison__year=year, date_livraison__month=month)
        )
        ids_rapport = set(qs_rapport.values_list("id", flat=True))

        # --- CALCUL AVEC updated_at (pour identifier les "intrus") ---
        qs_updated_at = base_qs.filter(
            Q(date_encaissement__isnull=True, date_livraison__isnull=True,
              updated_at__year=year, updated_at__month=month)
        )
        ids_updated_at = set(qs_updated_at.values_list("id", flat=True))

        # ===== RÉSULTATS =====
        self.stdout.write(f"📊 Colis dans DASHBOARD         : {len(ids_dashboard)}")
        self.stdout.write(f"📊 Colis dans RAPPORT AVANCÉ   : {len(ids_rapport)}")
        self.stdout.write(f"⚠️  Colis via updated_at seulement (sans date réelle) : {len(ids_updated_at)}\n")

        # Totaux
        total_dashboard = sum(get_net(c) for c in qs_dashboard.select_related("client"))
        total_rapport = sum(get_net(c) for c in qs_rapport.select_related("client"))
        total_updated = sum(get_net(c) for c in qs_updated_at.select_related("client"))

        self.stdout.write(self.style.SUCCESS(f"  TOTAL Dashboard  : {total_dashboard:,.0f} FCFA"))
        self.stdout.write(self.style.SUCCESS(f"  TOTAL Rapport    : {total_rapport:,.0f} FCFA"))
        self.stdout.write(self.style.WARNING(f"  TOTAL 'updated_at only' : {total_updated:,.0f} FCFA\n"))

        # === DETAIL des colis updated_at ===
        if qs_updated_at.exists():
            self.stdout.write(self.style.WARNING(
                "── Colis comptés via updated_at (sans date_livraison ni date_encaissement) ──"
            ))
            for c in qs_updated_at.select_related("client", "lot").order_by("updated_at"):
                net = get_net(c)
                self.stdout.write(
                    f"  [{c.reference}] {c.client} | "
                    f"updated_at: {c.updated_at.date() if c.updated_at else 'N/A'} | "
                    f"date_livraison: {c.date_livraison or 'VIDE'} | "
                    f"Net: {net:,.0f} FCFA"
                )
            self.stdout.write("")

        # === Colis dans Rapport mais pas dans Dashboard ===
        only_in_rapport = ids_rapport - ids_dashboard
        if only_in_rapport:
            self.stdout.write(self.style.ERROR("── Colis dans Rapport mais PAS dans Dashboard ──"))
            for c in base_qs.filter(id__in=only_in_rapport).select_related("client"):
                self.stdout.write(
                    f"  [{c.reference}] {c.client} | "
                    f"date_livraison: {c.date_livraison or 'VIDE'} | "
                    f"date_encaissement: {c.date_encaissement or 'VIDE'} | "
                    f"Net: {get_net(c):,.0f} FCFA"
                )
            self.stdout.write("")

        # === Colis dans Dashboard mais pas dans Rapport ===
        only_in_dashboard = ids_dashboard - ids_rapport
        if only_in_dashboard:
            self.stdout.write(self.style.ERROR("── Colis dans Dashboard mais PAS dans Rapport ──"))
            for c in base_qs.filter(id__in=only_in_dashboard).select_related("client"):
                self.stdout.write(
                    f"  [{c.reference}] {c.client} | "
                    f"date_livraison: {c.date_livraison or 'VIDE'} | "
                    f"date_encaissement: {c.date_encaissement or 'VIDE'} | "
                    f"Net: {get_net(c):,.0f} FCFA"
                )
        elif not only_in_rapport:
            self.stdout.write(self.style.SUCCESS(
                "✅ Aucune divergence : les deux vues comptabilisent exactement les mêmes colis !"
            ))

        self.stdout.write(
            self.style.HTTP_INFO(f"\n══════════════════════════════════════════════\n")
        )
