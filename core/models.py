from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


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


class Colis(TenantAwareModel):
    class Status(models.TextChoices):
        RECU = "RECU", _("Reçu Chine")
        EXPEDIE = "EXPEDIE", _("Expédié")
        ARRIVE = "ARRIVE", _("Arrivé Pays")
        LIVRE = "LIVRE", _("Livré Client")

    class TypeColis(models.TextChoices):
        STANDARD = "STANDARD", "Standard"
        TELEPHONE = "TELEPHONE", "Téléphone"
        ELECTRONIQUE = "ELECTRONIQUE", "Électronique"

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
        default=0,
    )
    longueur = models.DecimalField(
        max_digits=10, decimal_places=2, help_text=_("Longueur (cm)"), default=0
    )
    largeur = models.DecimalField(
        max_digits=10, decimal_places=2, help_text=_("Largeur (cm)"), default=0
    )
    hauteur = models.DecimalField(
        max_digits=10, decimal_places=2, help_text=_("Hauteur (cm)"), default=0
    )
    cbm = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text=_("Volume en m3 (Calculé auto: L*l*h/1000000)"),
        default=0,
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

    reference = models.CharField(max_length=50, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            import uuid

            # Génère une réf courte avec préfixe TS
            uid = str(uuid.uuid4()).split("-")[0].upper()
            self.reference = f"TS-{uid}"

        # Calcul auto du CBM si dimensions présentes
        if (
            getattr(self, "longueur", 0)
            and getattr(self, "largeur", 0)
            and getattr(self, "hauteur", 0)
        ):
            from decimal import Decimal

            vol_cm3 = (
                Decimal(self.longueur) * Decimal(self.largeur) * Decimal(self.hauteur)
            )
            self.cbm = vol_cm3 / Decimal("1000000")

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Colis {self.reference} - {self.client}"


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
