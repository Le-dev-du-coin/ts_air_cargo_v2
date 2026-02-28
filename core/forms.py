from django import forms
from django.contrib.auth.forms import AuthenticationForm


from django.core.exceptions import ValidationError


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Nom d'utilisateur ou Téléphone",
        widget=forms.TextInput(
            attrs={
                "class": "appearance-none rounded-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-t-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 focus:z-10 sm:text-sm",
                "placeholder": "Nom d'utilisateur ou Téléphone (ex: +223...)",
            }
        ),
    )

    error_messages = {
        "invalid_login": (
            "Veuillez entrer un nom d'utilisateur/téléphone et mot de passe corrects."
        ),
        "inactive": "Ce compte est inactif.",
    }

    def clean(self):
        try:
            return super().clean()
        except ValidationError as e:
            if hasattr(e, "code") and e.code == "invalid_login":
                username = self.cleaned_data.get("username")
                if username:
                    from django.contrib.auth import get_user_model
                    from django.db.models import Q

                    User = get_user_model()
                    user = User.objects.filter(
                        Q(phone=username) | Q(client_profile__telephone=username)
                    ).first()
                    # Si le username fourni correspond à un téléphone en base pour un non-client
                    if user and user.role != "CLIENT" and user.username != username:
                        raise ValidationError(
                            "Les Agents et Administrateurs doivent utiliser leur nom d'utilisateur.",
                            code="invalid_login",
                        )
            raise

    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(
            attrs={
                "class": "appearance-none rounded-none relative block w-full px-3 py-2 pr-10 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-b-md focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 focus:z-10 sm:text-sm",
                "placeholder": "Mot de passe",
            }
        ),
    )
