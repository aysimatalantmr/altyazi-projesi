from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/konusmaci/<str:room_code>/", consumers.SpeakerConsumer.as_asgi()),
    path("ws/ogrenci/<str:room_code>/", consumers.StudentConsumer.as_asgi()),
]
