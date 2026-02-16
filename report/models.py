from django.db import models
from core.models import User, Country
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class Depense(models.Model):
    class Categorie(models.TextChoices):
        LOYER = "LOYER", _("Loyer")
        ELECTRICITE = "ELECTRICITE", _("Électricité")
        EAU = "EAU", _("Eau")
        SALAIRE = "SALAIRE", _("Salaire")
        TRANSPORT = "TRANSPORT", _("Transport")
        NOURRITURE = "NOURRITURE", _("Nourriture")
        COMMUNICATION = "COMMUNICATION", _("Communication (Internet/Tel)")
        AUTRE = "AUTRE", _("Autre")

    date = models.DateField(default=timezone.now)
    description = models.CharField(max_length=255)
    montant = models.DecimalField(
        max_digits=10, decimal_places=0, help_text=_("Montant en FCFA")
    )
    categorie = models.CharField(
        max_length=50, choices=Categorie.choices, default=Categorie.AUTRE
    )
    piece_jointe = models.ImageField(upload_to="depenses/%Y/%m/", blank=True, null=True)

    enregistre_par = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="depenses_enregistrees"
    )
    pays = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="depenses")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = _("Dépense")
        verbose_name_plural = _("Dépenses")

    def __str__(self):
        return f"{self.date} - {self.description} ({self.montant} FCFA)"


class TransfertArgent(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", _("En attente")
        RECU = "RECU", _("Reçu")
        ANNULE = "ANNULE", _("Annulé")

    date = models.DateField(default=timezone.now)
    montant = models.DecimalField(
        max_digits=12, decimal_places=0, help_text=_("Montant transféré en FCFA")
    )
    description = models.TextField(blank=True, help_text=_("Note ou observation"))
    preuve_image = models.ImageField(
        upload_to="transferts/%Y/%m/",
        blank=True,
        null=True,
        help_text=_("Photo du reçu/bordereau"),
    )

    statut = models.CharField(
        max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE
    )

    enregistre_par = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="transferts_initis"
    )
    pays_expediteur = models.ForeignKey(
        Country, on_delete=models.PROTECT, related_name="transferts_sortants"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = _("Transfert d'argent")
        verbose_name_plural = _("Transferts d'argent")

    def __str__(self):
        return f"Transfert {self.montant} FCFA ({self.get_statut_display()})"
