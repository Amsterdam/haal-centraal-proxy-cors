from django.urls import path

from . import views

urlpatterns = [
    path("brp/personen", views.HaalCentraalBRP.as_view(), name="brp-proxy"),
]
