class LotsLivresView(LotsEnTransitView):
    """Historique des lots ayant des colis LIVRÉS ou PERDUS"""

    paginate_by = 10
    template_name = "mali/lots_livres.html"

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Lot.objects.none()

        query = self.request.GET.get("q")
        if query:
            # RECHERCHE GLOBALE PAR COLIS (Demande utilisateur)
            queryset = Colis.objects.filter(
                lot__destination=mali, status__in=["LIVRE", "PERDU"]
            )
            queryset = queryset.select_related("lot", "client", "client__user")
            queryset = queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "lot__numero",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)
            transport = self.request.GET.get("transport")
            if transport in ["CARGO", "EXPRESS", "BATEAU"]:
                queryset = queryset.filter(lot__type_transport=transport)
            
            month = self.request.GET.get("month")
            year = self.request.GET.get("year")
            if month and year:
                queryset = queryset.filter(updated_at__month=month, updated_at__year=year)

            return queryset.order_by("-updated_at")

        # AFFICHAGE PAR LOT (Sans recherche)
        # Un lot apparaît en livrés s'il a au moins un colis LIVRE ou PERDU
        queryset = (
            Lot.objects.filter(destination=mali, colis__status__in=["LIVRE", "PERDU"])
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                nb_colis_livre=Count(
                    "colis", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
                total_recettes_livre=Sum(
                    "colis__prix_final", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                )
                - Sum(
                    "colis__montant_jc", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
                # Nombre de colis payés en Chine parmi les livrés/perdus
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(
                        colis__status__in=["LIVRE", "PERDU"], colis__paye_en_chine=True
                    ),
                ),
                cbm_total_livre=Sum(
                    "colis__cbm", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
                poids_total_livre=Sum(
                    "colis__poids", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
            )
            .annotate(
                benefice_calcule=ExpressionWrapper(
                    Coalesce(
                        F("total_recettes_livre"), 0.0, output_field=DecimalField()
                    )
                    - Coalesce(F("frais_transport"), 0.0, output_field=DecimalField())
                    - Coalesce(F("frais_douane"), 0.0, output_field=DecimalField()),
                    output_field=DecimalField(),
                )
            )
            .filter(nb_colis_livre__gt=0)
            .distinct()
        )

        # Filtrage par type de transport
        transport = self.request.GET.get("transport")
        if transport in ["CARGO", "EXPRESS", "BATEAU"]:
            queryset = queryset.filter(type_transport=transport)

        # Filtrage par mois/année
        month = self.request.GET.get("month")
        year = self.request.GET.get("year")
        if month and year:
            queryset = queryset.filter(
                colis__date_livraison__month=month, colis__date_livraison__year=year
            )
        elif year:
            queryset = queryset.filter(colis__date_livraison__year=year)

        return queryset.order_by("-updated_at")


