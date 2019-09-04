from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('list-jobs', views.list_jobs, name='list-jobs'),
    path('queue-experiment', views.queue_experiment, name='queue-experiment'),
]
