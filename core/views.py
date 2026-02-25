from django.contrib.auth.views import LoginView
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView
from .forms import LoginForm


class IndexView(TemplateView):
    template_name = "index.html"


class CustomLoginView(LoginView):
    form_class = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        user = self.request.user
        if user.role == "GLOBAL_ADMIN":
            return reverse_lazy("admin:index")
        elif user.role in ["ADMIN_CHINE", "AGENT_CHINE"]:
            return reverse_lazy("chine:dashboard")
        elif user.role in ["ADMIN_MALI", "AGENT_MALI"]:
            return reverse_lazy("mali:dashboard")
        elif user.role in ["ADMIN_RCI", "AGENT_RCI"]:
            return reverse_lazy("ivoire:dashboard")
        elif user.role == "CLIENT":
            return reverse_lazy("customers:dashboard")
        # Add other role redirections here
        return reverse_lazy("index")


def logout_view(request):
    logout(request)
    return redirect("index")


from django.contrib.auth.decorators import user_passes_test


@user_passes_test(lambda u: u.is_superuser or u.role == "GLOBAL_ADMIN")
def flower_redirect(request):
    """
    Redirige les Super-Administrateurs vers le panel Flower de surveillance des tâches Celery.
    (Par défaut sur le port 5555 configuré dans start_flower.sh)
    """
    # Récupère l'IP/Domaine actuel du serveur et redirige vers le port 5555
    host = request.META.get("HTTP_HOST", "localhost").split(":")[0]
    return redirect(f"http://{host}:5555/")
