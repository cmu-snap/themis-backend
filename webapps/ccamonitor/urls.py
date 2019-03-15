from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('list-experiments', views.list_experiments, name='list-experiments'),
    path('queue-experiment', views.queue_experiment, name='queue-experiment'),
]
