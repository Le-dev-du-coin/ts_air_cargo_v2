from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import uuid


class Country(models.Model):
    code = models.CharField(
        max_length=2, unique=True, help_text=_("ISO Country Code (e.g. CN, ML, CI)")
    )
    name = models.CharField(max_length=100)
    currency_symbol = models.CharField(max_length=10, default="FCFA")

    class Meta:
        verbose_name = _("Country")
        verbose_name_plural = _("Countries")

    def __str__(self):
        return f"{self.name} ({self.code})"


class User(AbstractUser):
    class Role(models.TextChoices):
        GLOBAL_ADMIN = "GLOBAL_ADMIN", _("Global Admin")
        ADMIN_CHINE = "ADMIN_CHINE", _("Admin Chine")
        AGENT_CHINE = "AGENT_CHINE", _("Agent Chine")
        ADMIN_MALI = "ADMIN_MALI", _("Admin Mali")
        AGENT_MALI = "AGENT_MALI", _("Agent Mali")
        AGENT_RCI = "AGENT_RCI", _("Agent RCI")
        CLIENT = "CLIENT", _("Client")

    class RemunerationMode(models.TextChoices):
        SALAIRE = "SALAIRE", _("Salaire Fixe")
        COMMISSION = "COMMISSION", _("Commission (%)")

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CLIENT)
    country = models.ForeignKey(
        Country, on_delete=models.SET_NULL, null=True, blank=True, related_name="users"
    )
    phone = models.CharField(max_length=20, blank=True)
    remuneration_mode = models.CharField(
        max_length=20,
        choices=RemunerationMode.choices,
        default=RemunerationMode.SALAIRE,
        help_text=_("Type de rémunération de l'agent"),
    )
    remuneration_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_("Montant du salaire ou Pourcentage de commission"),
    )

    def __str__(self):
        return f"{self.username} ({self.role})"


class TenantAwareModel(models.Model):
    country = models.ForeignKey(
        Country, on_delete=models.PROTECT, related_name="%(class)s_related"
    )

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["country"]),
        ]


class Client(TenantAwareModel):
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100, blank=True)
    telephone = models.CharField(
        max_length=20, help_text=_("Format: +223... ou +225...")
    )
    adresse = models.TextField(blank=True)
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client_profile",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.telephone})"


class Lot(TenantAwareModel):
    class TypeTransport(models.TextChoices):
        CARGO = "CARGO", _("Cargo")
        EXPRESS = "EXPRESS", _("Express")
        BATEAU = "BATEAU", _("Bateau")

    class Status(models.TextChoices):
        OUVERT = "OUVERT", _("Ouvert")
        FERME = "FERME", _("Fermé")
        EN_TRANSIT = "EN_TRANSIT", _("En Transit")
        EXPEDIE = "EXPEDIE", _("Expédié")  # Fallback/Compat
        ARRIVE = "ARRIVE", _("Arrivé au Pays")
        DOUANE = "DOUANE", _("En Douane")
        DISPONIBLE = "DISPONIBLE", _("Disponible pour retrait")

    numero = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text=_("Généré automatiquement (ex: CARGO-2402-001)"),
    )
    destination = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="lots_destination",
        null=True,
        blank=True,
    )
    type_transport = models.CharField(
        max_length=20, choices=TypeTransport.choices, default=TypeTransport.CARGO
    )
    nb_colis = models.PositiveIntegerField(
        default=0,
        help_text=_(
            "Nombre de colis groupés dans ce lot (ex: 33 colis pour 415 cartons)"
        ),
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OUVERT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.numero:
            # Auto-generate number: TYPE-YYMM-SEQ
            prefix = f"{self.type_transport}-{timezone.now().strftime('%y%m')}"
            last_lot = (
                Lot.objects.filter(numero__startswith=prefix).order_by("numero").last()
            )
            if last_lot:
                try:
                    seq = int(last_lot.numero.split("-")[-1]) + 1
                except ValueError:
                    seq = 1
            else:
                seq = 1
            self.numero = f"{prefix}-{seq:03d}"
        super().save(*args, **kwargs)

    # Frais globaux
    frais_transport = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Coût du transport Chine -> Pays"),
    )
    frais_douane = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Frais de dédouanement à l'arrivée"),
    )

    note = models.TextField(
        blank=True,
        null=True,
        help_text=_("Observations (modifiable même après expédition)"),
    )
    photo = models.ImageField(
        upload_to="lots/%Y/%m/",
        blank=True,
        null=True,
        help_text=_("Photo globale du lot"),
    )

    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="lots_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    date_expedition = models.DateTimeField(null=True, blank=True)
    date_arrivee = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return (
            f"Lot {self.numero} ({self.get_type_transport_display()}) - {self.country}"
        )


class ClientLotTarif(models.Model):
    """
    Tarif spécial (conventionnel) négocié pour un client sur un lot spécifique.
    Ce tarif prime sur les tarifs standards et manuels.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="tarifs_speciaux"
    )
    lot = models.ForeignKey(
        Lot, on_delete=models.CASCADE, related_name="tarifs_speciaux", null=True, blank=True
    )
    destination = models.ForeignKey(
        "core.Country", on_delete=models.CASCADE, null=True, blank=True, related_name="tarifs_speciaux_recus"
    )
    type_transport = models.CharField(
        max_length=20, 
        choices=Lot.TypeTransport.choices, 
        null=True, 
        blank=True,
        help_text=_("S'applique uniquement à ce type de transport (Cargo/Express)")
    )
    prix_kilo = models.DecimalField(
        max_digits=10, decimal_places=2, help_text=_("Prix au kilo négocié")
    )
    admin_mali = models.ForeignKey(
        User, on_delete=models.PROTECT, help_text=_("Admin ayant validé le tarif")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("client", "lot")
        verbose_name = "Tarif Spécial Client/Lot"
        verbose_name_plural = "Tarifs Spéciaux Client/Lot"

    def __str__(self):
        return f"{self.client} - Lot {self.lot.numero} : {self.prix_kilo} FCFA/kg"


class Colis(TenantAwareModel):
    class Meta:
        verbose_name = _("Carton")
        verbose_name_plural = _("Cartons")

    class Status(models.TextChoices):
        RECU = "RECU", _("Reçu Chine")
        EXPEDIE = "EXPEDIE", _("Expédié")
        ARRIVE = "ARRIVE", _("Arrivé Pays")
        LIVRE = "LIVRE", _("Livré Client")

    class TypeColis(models.TextChoices):
        STANDARD = "STANDARD", "Standard"
        TELEPHONE = "TELEPHONE", "Téléphone"
        ELECTRONIQUE = "ELECTRONIQUE", "Électronique"
        MANUEL = "MANUEL", "Manuel"

    lot = models.ForeignKey(Lot, on_delete=models.CASCADE, related_name="colis")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="colis")
    type_colis = models.CharField(
        max_length=20, choices=TypeColis.choices, default=TypeColis.STANDARD
    )
    nombre_pieces = models.IntegerField(
        default=1, help_text=_("Nombre de pièces (requis pour Téléphone)")
    )
    description = models.CharField(max_length=255, blank=True)

    # Dimensions & Poids
    poids = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text=_("Poids (kg) - utilisé pour Cargo/Express"),
        null=True,
        blank=True,
    )
    cbm = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text=_("Volume en m3 (Saisie manuelle pour Bateau)"),
        default=0,
    )

    # Paramètres de tarification spéciale
    prix_kilo_manuel = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            "Prix au kilo défini manuellement par l'agent (pour TypeColis=Manuel)"
        ),
    )

    # Finance
    prix_transport = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text=_("Coût transport calculé"),
        default=0,
    )
    prix_final = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text=_("Prix total à payer par client"),
        default=0,
    )
    # Livraison & Paiement
    est_paye = models.BooleanField(default=False)
    paye_en_chine = models.BooleanField(
        default=False,
        help_text=_("Indique si le colis a été encaissé par l'agence en Chine"),
    )
    reste_a_payer = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_("Montant restant à payer par le client"),
    )
    mode_paiement = models.CharField(
        max_length=20,
        choices=[
            ("ESPECE", "Espèce"),
            ("ORANGE_MONEY", "Orange Money"),
            ("SARALI", "Sarali"),
        ],
        null=True,
        blank=True,
    )
    montant_jc = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=_("Montant Jeton Cédé (Remise/Ecart caisse)"),
    )
    mode_livraison = models.CharField(
        max_length=20,
        choices=[("AGENCE", "Retrait Agence"), ("DOMICILE", "Livraison Domicile")],
        default="AGENCE",
    )
    infos_recepteur = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Nom/Tel de la personne qui récupère (si différent du client)"),
    )
    commentaire_livraison = models.TextField(blank=True, null=True)
    whatsapp_notified = models.BooleanField(
        default=False, help_text=_("Notification WhatsApp envoyée/demandée")
    )
    notifie_fermeture = models.BooleanField(
        default=False,
        help_text=_("Notification 'lot fermé' déjà envoyée pour ce colis"),
    )

    photo = models.ImageField(upload_to="colis/%Y/%m/", blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RECU
    )

    # Sortie sous garantie (Agent Mali)
    sortie_sous_garantie = models.BooleanField(
        default=False,
        help_text=_("Indique si le colis a été sorti avec l'autorisation d'un garant"),
    )
    sortie_autorisee_par = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Nom du supérieur ou collègue ayant autorisé la sortie"),
    )

    # Colis ajouté manuellement par l'admin Mali (non enregistré côté Chine)
    ajoute_par_mali = models.BooleanField(
        default=False,
        help_text=_("Colis ajouté directement par l'admin Mali dans un lot arrivé"),
    )
    # Dates de livraison et d'encaissement
    date_livraison = models.DateField(null=True, blank=True, help_text=_("Date à laquelle le colis a été livré au client"))
    date_encaissement = models.DateField(null=True, blank=True, help_text=_("Date à laquelle le paiement a été encaissé"))

    reference = models.CharField(max_length=50, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            import uuid

            # Génère une réf courte avec préfixe TS
            uid = str(uuid.uuid4()).split("-")[0].upper()
            self.reference = f"TS-{uid}"

        # Recalculer les prix automatiquement
        self.recalculate_prices()

        super().save(*args, **kwargs)

    def recalculate_prices(self):
        """
        Recalcule le prix_transport et le prix_final en fonction du lot,
        du type de colis et des tarifs en vigueur.
        """
        # 1. Vérifier s'il existe un tarif spécial (conventionnel) pour ce client vers cette destination (global)
        # On vérifie si un tarif a le type de transport du lot OU si le type de transport du tarif est vide (applicable à tout)
        special_tarif = ClientLotTarif.objects.filter(
            client=self.client, destination=self.lot.destination
        ).filter(
            models.Q(type_transport=self.lot.type_transport) | models.Q(type_transport__isnull=True)
        ).first()

        if special_tarif and self.lot.type_transport != "BATEAU":
            # Si un tarif spécial est défini (Cargo/Express uniquement), il s'applique en priorité
            self.prix_transport = (self.poids or 0) * special_tarif.prix_kilo
            self.prix_final = self.prix_transport
            return

        # 2. Recherche du tarif standard pour la destination et le type de transport du lot
        try:
            tarif = Tarif.objects.get(
                destination=self.lot.destination, type_transport=self.lot.type_transport
            )
        except Tarif.DoesNotExist:
            tarif = None

        if self.type_colis == "MANUEL" and self.prix_kilo_manuel:
            self.prix_transport = (self.poids or 0) * self.prix_kilo_manuel
        elif self.type_colis == "TELEPHONE":
            # Pour le téléphone, on utilise le tarif spécifique téléphone s'il existe
            try:
                tarif_tel = Tarif.objects.get(
                    destination=self.lot.destination, type_transport="TELEPHONE"
                )
                self.prix_transport = self.nombre_pieces * tarif_tel.prix_piece
            except Tarif.DoesNotExist:
                if tarif:
                    self.prix_transport = self.nombre_pieces * tarif.prix_piece
                else:
                    self.prix_transport = 0
        elif self.lot.type_transport == "BATEAU":
            if tarif:
                self.prix_transport = (self.cbm or 0) * tarif.prix_cbm
            else:
                self.prix_transport = 0
        else:
            # Cargo / Express
            if tarif:
                self.prix_transport = (self.poids or 0) * tarif.prix_kilo
            else:
                self.prix_transport = 0

        # Par défaut, le prix final est égal au prix transport
        self.prix_final = self.prix_transport

    def __str__(self):
        return f"Carton {self.reference} - {self.client}"


class Tarif(TenantAwareModel):
    class TypeTarif(models.TextChoices):
        CARGO = "CARGO", _("Cargo")
        EXPRESS = "EXPRESS", _("Express")
        BATEAU = "BATEAU", _("Bateau")
        TELEPHONE = "TELEPHONE", _("Téléphone (Prix par pièce)")

    destination = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        related_name="tarifs",
        help_text=_("Pays de destination"),
    )
    type_transport = models.CharField(
        max_length=20, choices=TypeTarif.choices
    )  # Using distinct choices now

    prix_kilo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=_("Prix par Kg (Cargo/Express)"),
    )
    prix_cbm = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text=_("Prix par m3 (Bateau)")
    )
    prix_piece = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=_("Prix par pièce (Téléphone)"),
    )

    class Meta:
        verbose_name = _("Tarif")
        verbose_name_plural = _("Tarifs")
        constraints = [
            models.UniqueConstraint(
                fields=["country", "destination", "type_transport"],
                name="unique_tarif_per_dest_transport",
            )
        ]

    def __str__(self):
        return f"Tarif {self.type_transport} vers {self.destination}"


class BackgroundTask(TenantAwareModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("En attente")
        PROCESSING = "PROCESSING", _("En cours")
        SUCCESS = "SUCCESS", _("Réussi")
        FAILURE = "FAILURE", _("Échec")

    task_id = models.UUIDField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    parameters = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(null=True, blank=True)

    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="background_tasks"
    )

    def __str__(self):
        return f"{self.name} ({self.status})"

    class Meta:
        ordering = ["-created_at"]

class AvanceSalaire(models.Model):
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name="avances")
    montant = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    motif = models.CharField(max_length=255, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Avance {self.montant} - {self.agent.get_full_name()} ({self.date})"

    class Meta:
        ordering = ["-date", "-created_at"]
