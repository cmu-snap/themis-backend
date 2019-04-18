from django.db import models
from django.contrib.postgres.fields import JSONField

class Experiment(models.Model):
    CCALGS = (
        ('C', 'cubic'),
        ('B', 'bbr'),
        ('R', 'reno'),
    )
    website = models.CharField(max_length=2083)
    file_url = models.URLField()
    btlbw = models.PositiveIntegerField(blank=True)
    rtt = models.PositiveIntegerField(blank=True)
    competing_ccalg = models.CharField(blank=True, choices=CCALGS, max_length=1)
    request_date = models.DateTimeField(auto_now_add=True)

class Job(models.Model):
    TESTS = (
        ('I', 'iperf-website'),
        ('I16', 'iperf16-website'),
        ('A', 'apache-website'),
    )

    STATUSES = (
        ('C', 'completed'),
        ('M', 'failed to get metrics'),
        ('Q', 'queued'),
        ('R', 'running'),
        ('F', 'failed'),
    )
    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE)
    queue_size = models.PositiveIntegerField()
    test = models.CharField(default='I', choices=TESTS, max_length=3)
    competing_ccalg = models.CharField(max_length=5)
    
    status = models.CharField(default='Q', choices=STATUSES, max_length=1)
    job_id = models.CharField(null=True, max_length=100)
    request_date = models.DateTimeField(auto_now_add=True)
    exp_name = models.CharField(null=True, max_length=200)
    metrics = JSONField(null=True)

