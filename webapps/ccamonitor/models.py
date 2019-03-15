from django.db import models

# Create your models here.
class Experiment(models.Model):
    CCALGS = (
        ('C', 'cubic'),
        ('B', 'bbr'),
        ('R', 'reno'),
    )

    TESTS = (
        ('I', 'iperf-website'),
        ('I16', 'iperf16-website'),
        ('A', 'apache-website'),
    )

    STATUSES = (
        ('C', 'completed'),
        ('Q', 'queued'),
        ('R', 'running'),
        ('F', 'failed'),
    )

    website = models.CharField(max_length=2083)
    filename = models.URLField()
    btlbw = models.PositiveIntegerField(default=10, blank=True)
    rtt = models.PositiveIntegerField(default=75, blank=True)
    queue_size = models.IntegerField(blank=True)
    test = models.CharField(default='I', choices=TESTS, max_length=3)
    competing_ccalg = models.CharField(blank=True, choices=CCALGS, max_length=1)
    
    status = models.CharField(default='Q', choices=STATUSES, max_length=1)
    job_id = models.CharField(null=True, max_length=100)
    request_date = models.DateTimeField(auto_now_add=True)
    exp_name = models.CharField(null=True, max_length=200)

