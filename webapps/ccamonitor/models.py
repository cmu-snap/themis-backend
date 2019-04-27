from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
import uuid

class Experiment(models.Model):
    website = models.CharField(max_length=2083)
    file_url = models.URLField()
    btlbw = models.PositiveIntegerField(blank=True)
    rtt = models.PositiveIntegerField(blank=True)
    ccalgs = ArrayField(models.CharField(max_length=5), size=3, blank=False)
    request_date = models.DateTimeField(auto_now_add=True)
    finished_jobs = models.IntegerField(default=0)
    exp_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

class Graph(models.Model):
    exp = models.ForeignKey(Experiment, on_delete=models.CASCADE)
    graph = models.FileField(upload_to='graphics')
    competing_ccalg = models.CharField(max_length=5)


class Job(models.Model):
    TESTS = (
        ('I', 'iperf-website'),
        ('I16', 'iperf16-website'),
        ('A', 'apache-website'),
        ('V', 'video'),
    )

    STATUSES = (
        ('C', 'completed'),
        ('M', 'getting metrics'),
        ('D', 'downloading'),
        ('QD', 'queued for download'),
        ('QM', 'queued for metrics'),
        ('FM', 'failed to get metrics'),
        ('FD', 'failed fairness download'),
    )
    exp = models.ForeignKey(Experiment, on_delete=models.CASCADE)
    queue_size = models.PositiveIntegerField()
    test = models.CharField(default='I', choices=TESTS, max_length=3)
    competing_ccalg = models.CharField(max_length=5)
    
    status = models.CharField(default='QD', choices=STATUSES, max_length=2)
    job_id = models.CharField(null=True, max_length=100)
    request_date = models.DateTimeField(auto_now_add=True)
    exp_name = models.CharField(null=True, max_length=200)
    metrics = JSONField(null=True)
    num_tries = models.IntegerField(default=0)

