from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse


class RequireViewerLoginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if not settings.VISOR_REQUIRE_LOGIN or not match or match.namespace != "documents":
            return None
        if request.user.is_authenticated:
            return None
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "Se requiere iniciar sesión."}, status=401)
        return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
