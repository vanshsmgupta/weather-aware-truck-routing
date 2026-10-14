from django.urls import path, re_path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("geocode/", views.geocode),
    path("plans/", views.PlanView.as_view()),
    re_path(r"^plans/(?P<plan_id>[0-9a-f]{32})/heatmap/$", views.heatmap),
]
