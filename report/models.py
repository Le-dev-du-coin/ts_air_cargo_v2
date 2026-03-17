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
        MATERIELS = "MATERIELS", _("Matériels (Imprimante, Scotch, etc.)")
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
    is_china_indicative = models.BooleanField(
        default=False, 
        verbose_name=_("Dépense Chine (Indicatif)"),
        help_text=_("Si coché, ne sera pas pris en compte dans le solde de caisse Mali")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = _("Dépense")
        verbose_name_plural = _("Dépenses")

    def __str__(self):
        suffix = " (CHINE)" if self.is_china_indicative else ""
        return f"{self.date} - {self.description}{suffix} ({self.montant} FCFA)"


class TransfertArgent(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", _("En attente")
        RECU = "RECU", _("Reçu")
        ANNULE = "ANNULE", _("Annulé")

    class Destinataire(models.TextChoices):
        CHINE = "CHINE", _("Chine")
        GAOUSSOU = "GAOUSSOU", _("Gaoussou")

    date = models.DateField(default=timezone.now)
    montant = models.DecimalField(
        max_digits=12, decimal_places=0, help_text=_("Montant transféré en FCFA")
    )
    destinataire = models.CharField(
        max_length=20, choices=Destinataire.choices, default=Destinataire.CHINE
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


class PaiementAgent(models.Model):
    class MethodePaiement(models.TextChoices):
        ESPECES = "ESPECES", _("Espèces")
        VIREMENT = "VIREMENT", _("Virement Bancaire")
        MOBILE_MONEY = "MOBILE_MONEY", _("Mobile Money")
        AUTRE = "AUTRE", _("Autre")

    agent = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="paiements_recus"
    )
    montant = models.DecimalField(
        max_digits=10, decimal_places=0, help_text=_("Montant payé en FCFA")
    )
    date_paiement = models.DateTimeField(default=timezone.now)

    periode_mois = models.IntegerField(
        help_text=_("Mois de référence (ex: 3 pour Mars)")
    )
    periode_annee = models.IntegerField(help_text=_("Année de référence (ex: 2026)"))

    methode = models.CharField(
        max_length=50, choices=MethodePaiement.choices, default=MethodePaiement.ESPECES
    )
    note = models.TextField(
        blank=True, help_text=_("Référence de transfert, observation, etc.")
    )

    valide_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="paiements_valides"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_paiement", "-created_at"]
        verbose_name = _("Paiement Agent")
        verbose_name_plural = _("Paiements Agents")

    def __str__(self):
        return f"Paiement de {self.montant} FCFA à {self.agent.username} ({self.periode_mois}/{self.periode_annee})"
