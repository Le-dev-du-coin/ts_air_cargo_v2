
class Tarif(TenantAwareModel):
    """Tarifs configurables par l'Admin Chine par pays et type de transport"""
    type_transport = models.CharField(max_length=20, choices=Lot.TypeTransport.choices)
    
    # Tarifs de base
    prix_kilo = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text=_("Prix par Kg (pour Cargo/Express)"))
    prix_cbm = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text=_("Prix par m3 (pour Bateau)"))
    
    # Surcharges Spécifiques
    surcharge_telephone = models.DecimalField(default=0, max_digits=10, decimal_places=2, help_text=_("Prix fixe par téléphone"))
    surcharge_electronique = models.DecimalField(default=0, max_digits=10, decimal_places=2, help_text=_("Surcharge par unité électronique"))

    class Meta:
        # Un tarif unique par pays et par type de transport
        constraints = [
            models.UniqueConstraint(fields=['country', 'type_transport'], name='unique_tarif_per_country_transport')
        ]
        verbose_name = _("Tarif")
        verbose_name_plural = _("Tarifs")

    def __str__(self):
        return f"Tarif {self.type_transport} - {self.country}"
