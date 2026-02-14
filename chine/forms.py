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
        # Exclude China from country list (Client location)
        self.fields["country"].queryset = Country.objects.exclude(code="CN")
        mali = Country.objects.filter(code="ML").first()
        if mali:
            self.fields["country"].initial = mali


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
