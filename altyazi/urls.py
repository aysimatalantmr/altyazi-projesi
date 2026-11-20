from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "Akademik Altyazı Yönetimi"
admin.site.site_title = "Akademik Altyazı"
admin.site.index_title = "Terim sözlüğü ve oturumlar"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("giris/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("cikis/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("lectures.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
