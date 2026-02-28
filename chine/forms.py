from django import forms
from core.models import Client, Lot, Colis, Country
from django.utils.translation import gettext_lazy as _


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["nom", "prenom", "telephone", "country", "adresse"]
        widgets = {
            "nom": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Nom de famille",
                }
            ),
            "prenom": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Prénom",
                }
            ),
            "telephone": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "+223... ou +225...",
                }
            ),
            "country": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
                }
            ),
            "adresse": forms.Textarea(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["country"].queryset = Country.objects.exclude(code="CN")
        mali = Country.objects.filter(code="ML").first()
        if mali:
            self.fields["country"].initial = mali
        # Stocker le mot de passe généré pour y accéder depuis la vue
        self.generated_password = None

    @staticmethod
    def _normalize(text):
        """Supprime les accents et met en minuscule"""
        import unicodedata

        nfkd = unicodedata.normalize("NFKD", text or "")
        return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    @staticmethod
    def clean_telephone(self):
        telephone = self.cleaned_data.get("telephone")
        if telephone:
            telephone = telephone.strip().replace(" ", "")
            qs = Client.objects.filter(telephone=telephone)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    _("Un client avec ce numéro de téléphone existe déjà.")
                )
        return telephone

    def save(self, commit=True):
        client = super().save(commit=False)

        if not client.pk:
            # Génération du username unique : prenom.nom.XXXX
            from django.contrib.auth import get_user_model
            import random

            User = get_user_model()

            prenom = self._normalize(client.prenom or "")
            nom = self._normalize(client.nom or "")
            base = f"{prenom}.{nom}".strip(".")

            # Garantir l'unicité avec suffixe aléatoire
            username = f"{base}.{random.randint(1000, 9999)}"
            for _ in range(10):
                if not User.objects.filter(username=username).exists():
                    break
                username = f"{base}.{random.randint(1000, 9999)}"

            # Format de mot de passe conventionnel : TS + Téléphone
            telephone_propre = (
                client.telephone.replace(" ", "")
                if client.telephone
                else random.randint(100000, 999999)
            )
            password = f"TS{telephone_propre}"
            self.generated_password = password  # Accessible depuis la vue

            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=client.prenom or "",
                last_name=client.nom or "",
                email=f"{username}@tsair-cargo.com",
                role="CLIENT",
                country=client.country,
            )
            client.user = user

        if commit:
            client.save()

        return client


class ClientImportForm(forms.Form):
    csv_file = forms.FileField(label=_("Fichier CSV"))


class CountryForm(forms.ModelForm):
    class Meta:
        model = Country
        fields = ["code", "name", "currency_symbol"]
        widgets = {
            "code": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Ex: ML, CI, CN",
                }
            ),
            "name": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Nom du pays",
                }
            ),
            "currency_symbol": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Ex: FCFA",
                }
            ),
        }


class LotForm(forms.ModelForm):
    class Meta:
        model = Lot
        fields = [
            "destination",
            "type_transport",
            "frais_transport",
            "photo",
        ]
        widgets = {
            "destination": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
                }
            ),
            "type_transport": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
                }
            ),
            "frais_transport": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Transport Chine -> Pays",
                }
            ),
            "photo": forms.FileInput(
                attrs={
                    "class": "mt-1 block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exclude China from destination
        self.fields["destination"].queryset = Country.objects.exclude(code="CN")
        self.fields["destination"].required = True
        self.fields["type_transport"].required = True

        mali = Country.objects.filter(code="ML").first()
        if mali:
            self.fields["destination"].initial = mali


class LotNoteForm(forms.ModelForm):
    class Meta:
        model = Lot
        fields = ["note"]
        widgets = {
            "note": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Observations, problèmes...",
                }
            ),
        }


class ColisForm(forms.ModelForm):
    class Meta:
        model = Colis
        fields = [
            "client",
            "type_colis",
            "nombre_pieces",
            "description",
            "poids",
            "longueur",
            "largeur",
            "hauteur",
            "cbm",
            "prix_final",
            "est_paye",
            "photo",
        ]
        widgets = {
            "client": forms.Select(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
            "type_colis": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md",
                    "x-model": "type_colis",
                }
            ),
            "nombre_pieces": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "x-show": "type_colis == 'TELEPHONE'",
                    "x-model": "nombre_pieces",
                }
            ),
            "description": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "required": False,
                }
            ),
            "poids": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "step": "0.01",
                    "x-model": "poids",
                }
            ),
            "longueur": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "cm",
                    "x-model": "longueur",
                }
            ),
            "largeur": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "cm",
                    "x-model": "largeur",
                }
            ),
            "hauteur": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "cm",
                    "x-model": "hauteur",
                }
            ),
            "cbm": forms.NumberInput(
                attrs={
                    "class": "shadow-sm bg-gray-100 focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "readonly": True,
                    "x-model": "cbm",
                }
            ),
            "prix_final": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Calculé auto (modifiable)",
                }
            ),
            "est_paye": forms.CheckboxInput(
                attrs={
                    "class": "focus:ring-indigo-500 h-4 w-4 text-indigo-600 border-gray-300 rounded"
                }
            ),
            "photo": forms.FileInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        # Ne pas marquer photo comme required car compressed_photo peut être utilisé
        self.fields["photo"].required = False

    def clean(self):
        cleaned_data = super().clean()
        # Vérifier qu'une photo est fournie (soit via photo, soit via compressed_photo dans POST)
        photo = cleaned_data.get("photo")
        compressed_photo = self.data.get("compressed_photo")

        # Une photo est obligatoire : soit un fichier uploadé, soit une photo webcam compressée
        if not photo and not compressed_photo:
            self.add_error(
                "photo",
                "La photo du colis est obligatoire. Utilisez la webcam ou uploadez un fichier.",
            )

        return cleaned_data


from core.models import Tarif


class TarifForm(forms.ModelForm):
    class Meta:
        model = Tarif
        fields = [
            "destination",
            "type_transport",
            "prix_kilo",
            "prix_cbm",
            "prix_piece",
        ]
        widgets = {
            "destination": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
                }
            ),
            "type_transport": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md",
                    "x-model": "type_transport",
                }
            ),
            "prix_kilo": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
            "prix_cbm": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
            "prix_piece": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exclude China from destination
        self.fields["destination"].queryset = Country.objects.exclude(code="CN")

        mali = Country.objects.filter(code="ML").first()
        if mali:
            self.fields["destination"].initial = mali


from django.contrib.auth import get_user_model

User = get_user_model()


class AgentForm(forms.ModelForm):
    has_account = forms.BooleanField(
        label=_("Créer des identifiants (Accès interface)"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(
            attrs={
                "class": "focus:ring-indigo-500 h-4 w-4 text-indigo-600 border-gray-300 rounded",
                "x-model": "has_account",
            }
        ),
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        widget=forms.PasswordInput(
            attrs={
                "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                "placeholder": "Mot de passe",
            }
        ),
        required=False,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "country",
            "remuneration_mode",
            "remuneration_value",
            "password",
        ]
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
            "first_name": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Optionnel (auto si vide)",
                }
            ),
            "role": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
                }
            ),
            "country": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
                }
            ),
            "remuneration_mode": forms.Select(
                attrs={
                    "class": "mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
                }
            ),
            "remuneration_value": forms.NumberInput(
                attrs={
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                    "placeholder": "Montant ou %",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Rendre les noms obligatoires pour la génération d'email/identifiants
        self.fields["username"].required = (
            False  # Géré manuellement dans clean pour éviter erreurs browser si masqué
        )
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].required = False

        # Si édition, vérifier si l'user a un password utilisable
        if self.instance.pk:
            self.fields["has_account"].initial = self.instance.has_usable_password()

        # Filtrer les rôles CLIENT et GLOBAL_ADMIN pour les agents
        if "role" in self.fields:
            self.fields["role"].choices = [
                (key, value)
                for key, value in self.fields["role"].choices
                if key not in ["CLIENT", "GLOBAL_ADMIN", ""]
            ]

        if self.instance.pk:
            self.fields["password"].required = False
            self.fields["password"].help_text = (
                "Laissez vide pour ne pas changer le mot de passe."
            )
        else:
            # Check requirements dynamically in clean
            pass

    def clean(self):
        cleaned_data = super().clean()
        has_account = cleaned_data.get("has_account")
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")

        if has_account:
            if not username:
                self.add_error("username", _("Le nom d'utilisateur est requis."))
            if not self.instance.pk and not password:
                self.add_error("password", _("Le mot de passe est requis."))
        else:
            # Si pas de compte, on ignore les erreurs sur username/password créées par ModelForm
            if "username" in self._errors:
                del self._errors["username"]
            if "password" in self._errors:
                del self._errors["password"]

            # Si pas de compte, on génère un username technique si vide
            if not username:
                first_name = cleaned_data.get("first_name", "")
                last_name = cleaned_data.get("last_name", "")
                import random

                cleaned_data["username"] = (
                    f"{first_name.lower()}.{last_name.lower()}.{random.randint(100, 999)}"
                )

        # Génération de l'email si absent
        if not cleaned_data.get("email"):
            import random

            username = cleaned_data.get("username")
            if username:
                prefix = username.split("@")[0]
            else:
                first_name = cleaned_data.get("first_name", "").lower()
                last_name = cleaned_data.get("last_name", "").lower()
                prefix = f"{first_name}.{last_name}"

            cleaned_data["email"] = (
                f"{prefix}@{random.randint(100, 999)}.tsair-cargo.com"
            )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        has_account = self.cleaned_data.get("has_account")
        password = self.cleaned_data.get("password")

        if has_account and password:
            user.set_password(password)
        elif not has_account and not user.pk:
            user.set_unusable_password()

        if commit:
            user.save()
        return user
