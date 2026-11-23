from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles.views import serve
from django.urls import include, path, re_path

from web import views as dolares

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    path("dolares/", login_required(dolares.procesamiento), name="PR"),
    path("dolares/descargar-excel/", login_required(dolares.descargar_excel_dif), name="descargar_excel"),
    path("dolares/descargar-excel-nopresente/", login_required(dolares.descargar_excel_nopresente),
         name="descargar_excel_nopresente"),
    path("", include("conciliacion.urls")),
]

if not settings.DEBUG and not settings.EN_VERCEL:
    # Con DEBUG apagado runserver no sirve el CSS ni el JS; en Vercel los sirve su CDN tras collectstatic.
    urlpatterns += [re_path(r"^static/(?P<path>.*)$", serve, {"insecure": True})]
