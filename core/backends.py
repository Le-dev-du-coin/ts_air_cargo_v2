from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

UserModel = get_user_model()


class PhoneOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)

        try:
            # On cherche d'abord par le nom d'utilisateur (standard)
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            user = None

        # Si on ne le trouve pas par nom d'utilisateur, on cherche par numéro de téléphone
        if user is None:
            try:
                # On filtre spécifiquement sur le champ phone ou le telephone du profil client
                user = UserModel.objects.filter(
                    Q(phone=username) | Q(client_profile__telephone=username)
                ).first()
            except Exception:
                user = None

        if user:
            # RÈGLE MÉTIER : Connexion par téléphone autorisée UNIQUEMENT pour les CLIENTS
            is_phone = user.phone == username or (
                hasattr(user, "client_profile")
                and user.client_profile
                and user.client_profile.telephone == username
            )
            if is_phone and user.username != username:
                if user.role != "CLIENT":
                    # On refuse silencieusement ici, le formulaire de login captera l'échec et
                    # affichera le bon message d'erreur personnalisé
                    return None

            if user.check_password(password) and self.user_can_authenticate(user):
                return user

        return None
