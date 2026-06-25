import pytest
from core.models import Lot, Colis, Country, User, Client
from decimal import Decimal

@pytest.mark.django_db
class TestAirSeaIsolation:
    @pytest.fixture
    def setup_data(self):
        country = Country.objects.create(code="ML", name="Mali")
        user = User.objects.create(username="agent", role="ADMIN_CHINE")
        client = Client.objects.create(nom="Doe", prenom="John", telephone="+223000000", country=country)
        
        lot_avion = Lot.objects.create(
            type_transport="CARGO",
            destination=country,
            country=country,
            created_by=user
        )
        lot_bateau = Lot.objects.create(
            type_transport="BATEAU",
            destination=country,
            country=country,
            created_by=user
        )
        
        colis_avion = Colis.objects.create(
            lot=lot_avion,
            client=client,
            poids=Decimal("10.5"),
            country=country
        )
        colis_bateau = Colis.objects.create(
            lot=lot_bateau,
            client=client,
            cbm=Decimal("0.125"),
            country=country
        )
        colis_tel = Colis.objects.create(
            lot=lot_avion,
            client=client,
            type_colis="TELEPHONE",
            nombre_pieces=5,
            country=country
        )
        
        return {
            "lot_avion": lot_avion,
            "lot_bateau": lot_bateau,
            "colis_avion": colis_avion,
            "colis_bateau": colis_bateau,
            "colis_tel": colis_tel
        }

    def test_colis_managers(self, setup_data):
        assert Colis.objects.avion().count() == 2
        assert Colis.objects.bateau().count() == 1
        assert setup_data["colis_avion"] in Colis.objects.avion()
        assert setup_data["colis_bateau"] in Colis.objects.bateau()

    def test_lot_managers(self, setup_data):
        assert Lot.objects.avion().count() == 1
        assert Lot.objects.bateau().count() == 1

    def test_quantite_logistique(self, setup_data):
        assert setup_data["colis_avion"].quantite_logistique == Decimal("10.5")
        assert setup_data["colis_avion"].unite_logistique == "kg"
        
        assert setup_data["colis_bateau"].quantite_logistique == Decimal("0.125")
        assert setup_data["colis_bateau"].unite_logistique == "m³"
        
        assert setup_data["colis_tel"].quantite_logistique == 5
        assert setup_data["colis_tel"].unite_logistique == "pce"

    def test_quantite_logistique_display(self, setup_data):
        # On teste le display (attention au remplacement de . par , dans ma prop)
        assert "10,5 kg" in setup_data["colis_avion"].quantite_logistique_display
        assert "0,125 m³" in setup_data["colis_bateau"].quantite_logistique_display
        assert "5 pce" in setup_data["colis_tel"].quantite_logistique_display
