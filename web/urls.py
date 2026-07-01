from django.urls import path

from . import ifo, views

urlpatterns = [
    path("", views.home, name="home"),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    # IFO Admin surfaces
    path("ifo/rooms", ifo.rooms_list, name="ifo_rooms"),
    path("ifo/rooms/<str:code>", ifo.room_detail, name="ifo_room_detail"),
    path("ifo/rooms/<str:code>/poster", ifo.room_poster, name="ifo_room_poster"),
    path("ifo/rooms/<str:code>/qr.png", ifo.room_qr, name="ifo_room_qr"),
    path("ifo/live", ifo.live, name="ifo_live"),
    path("ifo/live/rows", ifo.live_rows, name="ifo_live_rows"),
    # PWA shell
    path("manifest.webmanifest", views.manifest),
    path("sw.js", views.service_worker),
    path("icon-<int:size>.png", views.icon),
]
