from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache


class ConfigurationNotification(models.Model):
    """
    Configuration globale des notifications (Singleton)
    Gère les clés API WaChap pour les différentes instances
    """

    # ---- API WaChap V4 ----
    # 1 clé secrète globale + 1 accountId par région (remplace les instance_id/access_token V1)

    wachap_v4_secret_key = models.CharField(
        "Clé Secrète WaChap V4 (globale)",
        max_length=255,
        blank=True,
        help_text="Clé Bearer commune à tous les comptes WaChap V4",
    )

    # AccountId par région (V4)
    wachap_account_chine = models.CharField(
        "Account ID Chine (V4)", max_length=255, blank=True
    )
    wachap_account_mali = models.CharField(
        "Account ID Mali (V4)", max_length=255, blank=True
    )
    wachap_account_cote_divoire = models.CharField(
        "Account ID Côte d'Ivoire (V4)", max_length=255, blank=True
    )
    wachap_account_system = models.CharField(
        "Account ID Système (V4)",
        max_length=255,
        blank=True,
        help_text="Utilisé pour les OTP et alertes administrateur",
    )

    # Configuration des rappels
    rappels_actifs = models.BooleanField(
        "Activer les rappels automatiques", default=False
    )
    delai_rappel_jours = models.IntegerField(
        "Délai avant rappel (jours)",
        default=3,
        help_text="Nombre de jours après l'arrivée du colis avant d'envoyer un rappel",
    )
    template_rappel = models.TextField(
        "Message de rappel (Adaptatif)",
        default=(
            "Bonjour {client_nom}, vous avez {nombre_colis} colis disponibles à l'agence depuis plus de {jours} jours.\n"
            "Références : {liste_ref}\n"
            "Total à payer : {total_montant}\n"
            "Merci de passer les récupérer."
        ),
        help_text="Variables : {client_nom}, {nombre_colis}, {jours}, {liste_ref}, {total_montant}, {numero_suivi}, {montant}",
    )

    # Sécurité
    security_code = models.CharField(
        "Code de sécurité (PIN)",
        max_length=50,
        default="0000",
        help_text="Code pour afficher/modifier les identifiants sensibles",
    )

    # Alertes
    developer_phone = models.CharField(
        "Téléphone Développeur (Alertes)",
        max_length=20,
        blank=True,
        help_text="Format international (+223...)",
    )

    admin_mali_phone = models.CharField(
        "Téléphone Admin Mali (Rapports journaliers)",
        max_length=20,
        blank=True,
        help_text="Si rempli, reçoit le rapport journalier WhatsApp à 23h50 (Cargo, Express, Bateau, Dépenses, Solde)",
    )

    test_phone_number = models.CharField(
        "Téléphone de Test (Override)",
        max_length=20,
        blank=True,
        help_text="Si rempli, TOUTES les notifications seront envoyées à ce numéro (utile pour le local).",
    )

    class Meta:
        verbose_name = "Configuration des Notifications"
        verbose_name_plural = "Configuration des Notifications"

    def __str__(self):
        return "Configuration Notifications"

    def save(self, *args, **kwargs):
        self.pk = 1  # Singleton
        super().save(*args, **kwargs)
        # Invalider le cache de config
        cache.delete("config_notification")

    @classmethod
    def get_solo(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class Notification(models.Model):
    TYPE_CHOICES = [
        ("whatsapp", "WhatsApp"),
        ("email", "Email"),  # Pour alertes admin/dev uniquement
    ]

    STATUT_CHOICES = [
        ("en_attente", "En attente"),
        ("envoye", "Envoyé"),
        ("echec", "Échec"),
        ("echec_permanent", "Échec Permanent"),
    ]

    CATEGORIE_CHOICES = [
        ("colis_recu", "Colis Reçu (Chine)"),
        ("lot_expedie", "Lot Expédié"),
        ("lot_arrive", "Lot Arrivé"),
        ("colis_livre", "Colis Livré"),
        ("rappel_colis", "Rappel Colis"),
        ("rapport_journalier", "Rapport Journalier Mali"),
        ("otp", "Code OTP"),
        ("alerte_admin", "Alerte Admin"),
        ("alerte_dev", "Alerte Développeur"),
        ("autre", "Autre"),
    ]

    # Destinataire (Client ou Admin)
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    telephone_destinataire = models.CharField(
        max_length=20, blank=True
    )  # Au cas où l'user est supprimé ou non lié
    email_destinataire = models.EmailField(blank=True)

    # Contenu
    type_notification = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default="whatsapp"
    )
    categorie = models.CharField(
        max_length=50, choices=CATEGORIE_CHOICES, default="autre"
    )
    titre = models.CharField(max_length=200, blank=True)
    message = models.TextField()

    # Liaison métier (Loose coupling ou FKs si possible)
    # On utilise des FKs nullable pour garder l'intégrité référentielle mais ne pas bloquer si l'app 'chine' change
    colis = models.ForeignKey(
        "core.Colis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    lot = models.ForeignKey(
        "core.Lot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )

    # Suivi technique
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default="en_attente"
    )
    message_id_externe = models.CharField("ID WaChap/Email", max_length=100, blank=True)
    erreur_envoi = models.TextField(blank=True)
    nombre_tentatives = models.IntegerField(default=0)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_envoi = models.DateTimeField(null=True, blank=True)
    prochaine_tentative = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_creation"]
        indexes = [
            models.Index(fields=["statut"]),
            models.Index(fields=["categorie"]),
            models.Index(fields=["date_creation"]),
        ]

    def __str__(self):
        return f"{self.get_type_notification_display()} - {self.destinataire} ({self.get_statut_display()})"

    def marquer_comme_envoye(self, message_id):
        self.statut = "envoye"
        self.message_id_externe = message_id
        self.date_envoi = timezone.now()
        self.save()

    def marquer_comme_echec(self, erreur, erreur_type="temporaire"):
        self.erreur_envoi = str(erreur)
        if erreur_type == "permanent" or self.nombre_tentatives >= 5:
            self.statut = "echec_permanent"
        else:
            self.statut = "echec"
            # Backoff exponentiel simple pour la prochaine tentative
            delay = (2**self.nombre_tentatives) * 60  # secondes
            self.prochaine_tentative = timezone.now() + timezone.timedelta(
                seconds=delay
            )
        self.save()
