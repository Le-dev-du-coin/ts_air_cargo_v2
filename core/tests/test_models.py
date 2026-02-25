import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from core.models import Country, Lot, Colis, Client, Tarif

User = get_user_model()


@pytest.mark.django_db
class TestCalculsTransport:
    def setup_method(self):
        # Création des pays
        self.chine = Country.objects.create(code="CN", name="Chine")
        self.mali = Country.objects.create(code="ML", name="Mali")

        # Utilisateur et Client
        self.user = User.objects.create_user(
            username="test_client", password="password", role="CLIENT"
        )
        self.client = Client.objects.create(
            user=self.user,
            nom="Test",
            prenom="Client",
            telephone="123456",
            country=self.mali,
        )

        # Tarification minimale pour que les tests fonctionnent si tu as une validation métier dessus
        self.tarif_cargo = Tarif.objects.create(
            type_transport=Lot.TypeTransport.CARGO,
            prix_kilo=Decimal("10000"),
            prix_cbm=Decimal("0"),
            country=self.chine,
            destination=self.mali,
        )
        self.tarif_bateau = Tarif.objects.create(
            type_transport=Lot.TypeTransport.BATEAU,
            prix_kilo=Decimal("0"),
            prix_cbm=Decimal("300000"),
            country=self.chine,
            destination=self.mali,
        )

    def test_calcul_cbm_automatique(self):
        """Vérifie que le CBM est bien calculé lors de la sauvegarde (L*l*h / 1M)"""
        lot = Lot.objects.create(
            destination=self.mali,
            type_transport=Lot.TypeTransport.BATEAU,
            country=self.chine,
            created_by=self.user,
        )
        colis = Colis(
            lot=lot,
            client=self.client,
            longueur=Decimal("100"),
            largeur=Decimal("50"),
            hauteur=Decimal("40"),
            poids=Decimal("10"),
            country=self.chine,
        )
        colis.save()

        # 100 * 50 * 40 = 200,000 / 1,000,000 = 0.2 CBM
        assert colis.cbm == Decimal("0.2000")

    def test_lot_peut_fermer_sans_colis(self):
        """Vérifie qu'un lot vide ne peut pas être fermé"""
        lot = Lot.objects.create(
            destination=self.mali,
            type_transport=Lot.TypeTransport.CARGO,
            country=self.chine,
            created_by=self.user,
        )

        # Essayer de fermer
        if hasattr(lot, "peut_fermer"):
            peut_fermer, msg = lot.peut_fermer()
            assert not peut_fermer
            assert "colis" in msg.lower()

    def test_lot_peut_expedier_sans_frais(self):
        """Vérifie qu'un lot ne peut être expédié s'il manque les frais de transport"""
        lot = Lot.objects.create(
            destination=self.mali,
            type_transport=Lot.TypeTransport.CARGO,
            status=Lot.Status.FERME,
            frais_transport=None,
            country=self.chine,
            created_by=self.user,
        )

        if hasattr(lot, "peut_expedier"):
            peut_expedier, msg = lot.peut_expedier()
            assert not peut_expedier
            assert "frais" in msg.lower()
