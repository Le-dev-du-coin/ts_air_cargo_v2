from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

class Country(models.Model):
    code = models.CharField(max_length=2, unique=True, help_text=_("ISO Country Code (e.g. CN, ML, CI)"))
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
        ADMIN_RCI = "ADMIN_RCI", _("Admin RCI")
        AGENT_RCI = "AGENT_RCI", _("Agent RCI")
        CLIENT = "CLIENT", _("Client")
        
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CLIENT)
    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True, related_name="users")
    phone = models.CharField(max_length=20, blank=True)
    
    def __str__(self):
        return f"{self.username} ({self.role})"

class TenantAwareModel(models.Model):
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="%(class)s_related")
    
    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['country']),
        ]

class Client(TenantAwareModel):
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100, blank=True)
    telephone = models.CharField(max_length=20, help_text=_("Format: +223... ou +225..."))
    email = models.EmailField(blank=True)
    adresse = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.telephone})"

class Lot(TenantAwareModel):
    class TypeTransport(models.TextChoices):
        AERIEN = "AERIEN", _("Aérien")
        MARITIME = "MARITIME", _("Maritime")

    class Status(models.TextChoices):
        OUVERT = "OUVERT", _("Ouvert")
        FERME = "FERME", _("Fermé")
        EXPEDIE = "EXPEDIE", _("Expédié")
        ARRIVE = "ARRIVE", _("Arrivé au Pays")
        DOUANE = "DOUANE", _("En Douane")
        DISPONIBLE = "DISPONIBLE", _("Disponible pour retrait")

    numero = models.CharField(max_length=50, unique=True, help_text=_("Généré automatiquement (ex: ML-2402-001)"))
    type_transport = models.CharField(max_length=20, choices=TypeTransport.choices, default=TypeTransport.AERIEN)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OUVERT)
    
    # Frais globaux
    frais_transport = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text=_("Coût du transport Chine -> Pays"))
    frais_douane = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text=_("Frais de dédouanement à l'arrivée"))
    
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="lots_created")
    created_at = models.DateTimeField(auto_now_add=True)
    date_expedition = models.DateTimeField(null=True, blank=True)
    date_arrivee = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Lot {self.numero} ({self.get_type_transport_display()}) - {self.country}"

class Colis(TenantAwareModel):
    class Status(models.TextChoices):
        RECU = "RECU", _("Reçu Chine")
        EXPEDIE = "EXPEDIE", _("Expédié")
        ARRIVE = "ARRIVE", _("Arrivé Pays")
        LIVRE = "LIVRE", _("Livré Client")

    lot = models.ForeignKey(Lot, on_delete=models.CASCADE, related_name="colis")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="colis")
    description = models.CharField(max_length=255)
    
    # Dimensions & Poids
    poids = models.DecimalField(max_digits=10, decimal_places=2, help_text=_("Poids en kg"), default=0)
    cbm = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, help_text=_("Volume en m3 (Maritime)"))
    
    # Finance
    prix_transport = models.DecimalField(max_digits=12, decimal_places=2, help_text=_("Coût transport calculé"), default=0)
    prix_final = models.DecimalField(max_digits=12, decimal_places=2, help_text=_("Prix total à payer par client"), default=0)
    est_paye = models.BooleanField(default=False)
    
    photo = models.ImageField(upload_to="colis/%Y/%m/", blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECU)
    
    reference = models.CharField(max_length=50, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            import uuid
            self.reference = str(uuid.uuid4()).split('-')[0].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Colis {self.reference} - {self.client}"
