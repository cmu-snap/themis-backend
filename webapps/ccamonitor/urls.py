from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('queue-experiment', views.queue_experiment, name='queue-experiment'),
]
