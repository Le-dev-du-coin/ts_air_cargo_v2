from django import forms
from core.models import Client, Lot, Colis, Country
from django.utils.translation import gettext_lazy as _


class ClientForm(forms.ModelForm):
    username = forms.CharField(
        label=_("Nom d'utilisateur"),
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                "placeholder": "Identifiant de connexion",
            }
        ),
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md",
                "placeholder": "Mot de passe",
            }
        ),
    )

    class Meta:
        model = Client
        fields = [
            "nom",
            "prenom",
            "telephone",
            "country",
            "adresse",
            "username",
            "password",
        ]  # Added username/password to fields list (if they are not model fields, they are ignored by ModelForm save, but included in form validation)
        # Actually for ModelForm, non-model fields should not be in Meta.fields if specific to form.
        # But wait, fields list controls order.
        # I'll keep them out of Meta.fields and put them in class definition, they will appear.
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
        # Exclude China from country list (Client location)
        self.fields["country"].queryset = Country.objects.exclude(code="CN")
        mali = Country.objects.filter(code="ML").first()
        if mali:
            self.fields["country"].initial = mali

        if not self.instance.pk:
            self.fields["username"].required = True
            self.fields["password"].required = True
        else:
            # Edit mode: hide username/password or make optional?
            # User might want to see them? But password is hashed.
            # For now, let's keep them hidden or optional in edit.
            # Requirement was "creation", not update.
            # I will hide them in update for simplicity unless requested.
            if self.instance.user:
                self.fields["username"].initial = self.instance.user.username
                self.fields["username"].disabled = True  # Cannot change username easily
                self.fields["password"].widget = (
                    forms.HiddenInput()
                )  # Don't allow password change here for now
            else:
                pass

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if username:
            # Check if username exists (exclude current user if editing)
            # But Client is not User model.
            from django.contrib.auth import get_user_model

            User = get_user_model()
            if User.objects.filter(username=username).exists():
                # If we are editing and this is our user, it's fine.
                if (
                    self.instance.pk
                    and self.instance.user
                    and self.instance.user.username == username
                ):
                    return username
                raise forms.ValidationError(_("Ce nom d'utilisateur est déjà pris."))
        return username

    def save(self, commit=True):
        client = super().save(commit=False)

        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if not client.pk and username and password:
            # Create user
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=client.prenom,
                last_name=client.nom,
                email="",  # Optional
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
        fields = ["destination", "type_transport", "frais_transport", "photo"]
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
                    "placeholder": "Automatique",
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
    password = forms.CharField(
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
                    "class": "shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md"
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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
            self.fields["password"].required = True

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user
