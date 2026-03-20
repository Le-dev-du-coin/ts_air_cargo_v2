from django import forms
from core.models import Colis, AvanceSalaire, User
from notification.models import ConfigurationNotification

class ColisUpdateMaliForm(forms.ModelForm):
    class Meta:
        model = Colis
        fields = ["type_colis", "nombre_pieces", "poids", "cbm", "prix_kilo_manuel"]
        widgets = {
            "type_colis": forms.Select(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                }
            ),
            "nombre_pieces": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "min": "1",
                }
            ),
            "poids": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "step": "0.01",
                }
            ),
            "cbm": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "step": "0.0001",
                }
            ),
            "prix_kilo_manuel": forms.NumberInput(
                attrs={
                    "class": "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm",
                    "step": "0.1",
                }
            ),
        }
class ColisLivreMaliForm(forms.ModelForm):
    class Meta:
        model = Colis
        fields = [
            "mode_livraison",
            "infos_recepteur",
            "commentaire_livraison",
            "reste_a_payer",
            "mode_paiement",
            "montant_jc",
            "sortie_sous_garantie",
            "sortie_autorisee_par",
        ]
        widgets = {
            "mode_livraison": forms.RadioSelect(),
            "commentaire_livraison": forms.Textarea(attrs={"rows": 2}),
            "mode_paiement": forms.Select(attrs={"class": "w-full rounded-md border-gray-300"}),
            "reste_a_payer": forms.NumberInput(attrs={"class": "w-full rounded-md border-gray-300"}),
            "montant_jc": forms.NumberInput(attrs={"class": "w-full rounded-md border-gray-300"}),
        }

class NotificationConfigForm(forms.ModelForm):
    """
    Formulaire agent Mali : rappels automatiques + numéro de rapport journalier.
    Les credentials API WaChap sont gérés par l'administrateur.
    """

    class Meta:
        model = ConfigurationNotification
        fields = [
            "rappels_actifs",
            "delai_rappel_jours",
            "template_rappel",
            "admin_mali_phone",
            "admin_mali_phone_2",
            "admin_mali_phone_3",
        ]
        widgets = {
            "template_rappel": forms.Textarea(
                attrs={"rows": 4, "class": "w-full border-gray-300 rounded-md"}
            ),
            "delai_rappel_jours": forms.NumberInput(
                attrs={"class": "w-full border-gray-300 rounded-md"}
            ),
            "admin_mali_phone": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "+223XXXXXXXX",
                }
            ),
            "admin_mali_phone_2": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "+223XXXXXXXX",
                }
            ),
            "admin_mali_phone_3": forms.TextInput(
                attrs={
                    "class": "w-full border-gray-300 rounded-md",
                    "placeholder": "+223XXXXXXXX",
                }
            ),
        }

class AvanceSalaireForm(forms.ModelForm):
    class Meta:
        model = AvanceSalaire
        fields = ['agent', 'montant', 'date', 'motif']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full border-gray-300 rounded-md'}),
            'montant': forms.NumberInput(attrs={'class': 'w-full border-gray-300 rounded-md', 'min': '0'}),
            'motif': forms.TextInput(attrs={'class': 'w-full border-gray-300 rounded-md', 'placeholder': 'Ex: Avance sur salaire...'}),
            'agent': forms.Select(attrs={'class': 'w-full border-gray-300 rounded-md'})
        }

    def __init__(self, *args, **kwargs):
        self.country = kwargs.pop('country', None)
        super().__init__(*args, **kwargs)
        if self.country:
            self.fields['agent'].queryset = User.objects.filter(country=self.country).exclude(role='CLIENT')
        
        # Afficher Nom + Prénom simple au lieu du username
        self.fields['agent'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name}".strip() or obj.username


class MaliAddColisForm(forms.Form):
    """Formulaire pour ajouter un colis manquant dans un lot arrivé (Ajout Admin Mali)"""
    from core.models import Client

    client = forms.ModelChoiceField(
        queryset=None,  # Sera injecté dans __init__
        label="Client",
        widget=forms.Select(attrs={'class': 'w-full border-gray-300 rounded-xl'})
    )
    type_colis = forms.ChoiceField(
        choices=[('STANDARD','Standard'), ('TELEPHONE','Téléphone'), ('ELECTRONIQUE','Électronique'), ('MANUEL','Manuel')],
        label="Type de colis",
        widget=forms.Select(attrs={'class': 'w-full border-gray-300 rounded-xl'})
    )
    poids = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False, min_value=0,
        label="Poids (kg)",
        widget=forms.NumberInput(attrs={'class': 'w-full border-gray-300 rounded-xl', 'step': '0.01', 'placeholder': '0.00'})
    )
    cbm = forms.DecimalField(
        max_digits=10, decimal_places=4, required=False, min_value=0, initial=0,
        label="Volume CBM (m³) - Bateau uniquement",
        widget=forms.NumberInput(attrs={'class': 'w-full border-gray-300 rounded-xl', 'step': '0.0001', 'placeholder': '0.0000'})
    )
    nombre_pieces = forms.IntegerField(
        min_value=1, initial=1, required=False,
        label="Nombre de pièces (Téléphone)",
        widget=forms.NumberInput(attrs={'class': 'w-full border-gray-300 rounded-xl', 'min': '1'})
    )
    prix_final = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0,
        label="Prix final (FCFA)",
        widget=forms.NumberInput(attrs={'class': 'w-full border-gray-300 rounded-xl', 'placeholder': '0'})
    )
    description = forms.CharField(
        required=False, max_length=255,
        label="Description (optionnel)",
        widget=forms.TextInput(attrs={'class': 'w-full border-gray-300 rounded-xl', 'placeholder': 'Décription du colis...'})
    )

    def __init__(self, *args, **kwargs):
        country = kwargs.pop('country', None)
        super().__init__(*args, **kwargs)
        if country:
            from core.models import Client
            self.fields['client'].queryset = Client.objects.filter(country=country)

class MaliAgentForm(forms.ModelForm):
    acces_systeme = forms.BooleanField(
        required=False,
        initial=True,
        label="Autoriser l'accès au système"
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "username", "password", "remuneration_mode", "remuneration_value", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].required = False
        self.fields["password"].required = False

        if self.instance and self.instance.pk:
            self.fields["acces_systeme"].initial = self.instance.is_active

    def clean(self):
        import uuid
        cleaned_data = super().clean()
        acces_systeme = cleaned_data.get("acces_systeme")
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")

        if acces_systeme:
            if not self.instance.pk:
                if not username:
                    self.add_error("username", "Le nom d'utilisateur est obligatoire pour un accès système.")
                if not password:
                    self.add_error("password", "Le mot de passe est obligatoire pour un accès système.")
        else:
            if not self.instance.pk:
                if not username:
                    cleaned_data["username"] = f"agent_{uuid.uuid4().hex[:8]}"
                if not password:
                    cleaned_data["password"] = User.objects.make_random_password()
            cleaned_data["is_active"] = False

        return cleaned_data
