from django.urls import path

from . import views

app_name = "lectures"

urlpatterns = [
    path("", views.home, name="home"),
    path("oda/<str:room_code>/", views.student_room, name="student_room"),
    path("oda/<str:room_code>/transkript.txt", views.transcript_txt, name="transcript_txt"),
    path("konusmaci/", views.speaker_dashboard, name="speaker_dashboard"),
    path("konusmaci/<str:room_code>/", views.speaker_room, name="speaker_room"),
]
