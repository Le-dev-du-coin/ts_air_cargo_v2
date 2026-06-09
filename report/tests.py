from django.test import TestCase
from decimal import Decimal
from django.utils import timezone
from datetime import datetime
from core.models import Country, Lot, Colis, Client, User, EncaissementColis, AvoirMouvement
from report.models import Depense, TransfertArgent
from report.finance_engine import FinanceEngine

class FinanceEngineTests(TestCase):
    def setUp(self):
        # Setup countries
        self.mali = Country.objects.create(name="Mali", code="ML")
        self.chine = Country.objects.create(name="Chine", code="CN")
        
        # Setup User
        self.admin = User.objects.create_user(username="admin", password="pass", role="GLOBAL_ADMIN")
        self.agent_user = User.objects.create_user(username="testuser", password="pass")
        # Important: Le profil client est créé via le modèle Client qui pointe vers User
        self.client = Client.objects.create(user=self.agent_user, country=self.mali)
        
        # Setup Tarif (requis pour que Colis.save() ne mette pas le prix à 0)
        from core.models import Tarif
        Tarif.objects.create(
            country=self.mali,
            destination=self.mali,
            type_transport="CARGO",
            prix_kilo=1000
        )
        
        # Date fixe: 15 Mai 2026
        self.test_date = timezone.make_aware(datetime(2026, 5, 15))
        
        # Setup Lot
        self.lot = Lot.objects.create(
            numero="LOT-2605-001",
            country=self.mali,
            destination=self.mali,
            type_transport="CARGO",
            status="ARRIVE",
            date_arrivee=self.test_date,
            created_by=self.admin
        )
        
        # Setup Colis
        # Note: recalculate_prices dans save() peut échouer si manque des infos
        self.colis = Colis.objects.create(
            reference="COLIS001",
            country=self.mali,
            lot=self.lot,
            client=self.client,
            prix_final=10000,
            poids=10,
            type_colis="STANDARD"
        )

    def test_daily_summary_receipts(self):
        """Test que les encaissements simples sont bien comptabilisés."""
        today = self.test_date.date()
        EncaissementColis.objects.create(
            colis=self.colis,
            montant=5000,
            date=today,
            methode="ESPECE",
            enregistre_par=self.admin
        )
        
        summary = FinanceEngine.get_daily_summary(today, self.mali)
        self.assertEqual(summary["total_encaissements_colis"], 5000)

    def test_monthly_performance_profit(self):
        """Test du calcul du bénéfice net mensuel."""
        perf = FinanceEngine.get_monthly_performance(2026, 5, "ML")
        
        # CA Net = 10000 (colis créé dans setUp)
        # Fret = 0, Douane = 0 (par défaut dans Lot si non précisé)
        self.assertEqual(perf["chiffre_affaires"], 10000)
        self.assertEqual(perf["benefice_brut"], 10000)
        
        # Ajout d'une dépense
        Depense.objects.create(
            pays=self.mali,
            montant=1500,
            date=self.test_date.date(),
            is_china_indicative=False,
            enregistre_par=self.admin
        )
        
        perf_v2 = FinanceEngine.get_monthly_performance(2026, 5, "ML")
        # Bénéfice Net = 10000 - 1500 = 8500
        self.assertEqual(perf_v2["benefice_net"], 8500)

    def test_transfer_exclusion_from_profit(self):
        """Vérifie qu'un transfert d'argent n'impacte PAS le bénéfice."""
        # Transfert = 5000
        TransfertArgent.objects.create(
            pays_expediteur=self.mali,
            montant=5000,
            date=self.test_date.date(),
            enregistre_par=self.admin
        )
        
        perf = FinanceEngine.get_monthly_performance(2026, 5, "ML")
        # Le bénéfice doit rester à 10000 (setup)
        self.assertEqual(perf["benefice_net"], 10000)

    def test_daily_summary_balance_with_transfer(self):
        """Vérifie qu'un transfert impacte par contre le SOLDE de caisse."""
        today = self.test_date.date()
        
        # Recette 10000 (setup) - Non, setup ne crée pas d'encaissement, juste un colis
        EncaissementColis.objects.create(
            colis=self.colis,
            montant=10000,
            date=today,
            methode="ESPECE",
            enregistre_par=self.admin
        )
        
        # Transfert 4000
        TransfertArgent.objects.create(
            pays_expediteur=self.mali,
            montant=4000,
            date=today,
            enregistre_par=self.admin
        )
        
        summary = FinanceEngine.get_daily_summary(today, self.mali)
        # Recette 10000, Sortie 4000 -> Solde 6000
        self.assertEqual(summary["total_recettes_jour"], 10000)
        self.assertEqual(summary["total_sorties_jour"], 4000)
        self.assertEqual(summary["solde_caisse_actuel"], 6000)
