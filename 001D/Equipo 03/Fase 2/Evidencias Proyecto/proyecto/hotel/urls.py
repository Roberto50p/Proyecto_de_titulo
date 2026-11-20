from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.urls import include, path

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
