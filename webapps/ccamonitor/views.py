from django.shortcuts import render, redirect
from ccamonitor.forms import *
from ccamonitor.ccalg_agent import *
from rq import get_current_job
import django_rq
import json

def index(request):
    context = {'form': ExperimentForm()}
    return render(request, 'ccamonitor/queue.html', context)

@django_rq.job
def run_experiment(inputs):
    job = get_current_job()
    exp = Experiment.objects.get(job_id=job.get_id())
    exp.status = 'R'
    exp.save()
    try:
        exp_name = run_ccalg_fairness(inputs)
        exp.exp_name = exp_name
        if run_fairness_snakefile(exp_name) == 0:
            exp.status = 'C'
            try:
                with open('/tmp/data-processed/{}.metric'.format(exp_name)) as json_file:
                    exp.metrics = json.load(json_file)
            except EnvironmentError:
                exp.status = 'M'
        else:
            exp.status = 'M'
    except Exception as e:
        exp.status = 'F'
    exp.save()

def queue_experiment(request):
    QUEUE_SIZES = [32, 64, 512]
    form = ExperimentForm(request.POST)
    context = {'form': ExperimentForm()}

    if form.is_valid():
        website = form.cleaned_data['website']
        file_url = form.cleaned_data['file_url']
        btlbw = form.cleaned_data['btlbw']
        if btlbw is None:
            btlbw = 10
        rtt = form.cleaned_data['rtt']
        if rtt is None:
            rtt = 75

        queue_size = form.cleaned_data['queue_size']
        test = form.cleaned_data['test']
        competing_ccalg = form.cleaned_data['competing_ccalg']

        ntwrk_conditions = [(btlbw, rtt, queue_size)]
        # If queue_size unspecified, run once for each size in QUEUE_SIZES
        if queue_size is None:
            ntwrk_conditions = [(btlbw, rtt, size) for size in QUEUE_SIZES]

        ccalgs = [competing_ccalg]
        if competing_ccalg == '':
            ccalgs = ['C', 'B']

        for (btlbw, rtt, size) in ntwrk_conditions:
            for ccalg in ccalgs:
                exp = Experiment.objects.create(
                        website=website,
                        file_url=file_url,
                        btlbw=btlbw,
                        rtt=rtt,
                        queue_size=size,
                        test=test,
                        competing_ccalg=ccalg
                        )
                inputs = {
                    'website': website,
                    'file_url': file_url,
                    'btlbw': btlbw,
                    'rtt': rtt,
                    'queue_size': size,
                    'test': exp.get_test_display(),
                    'competing_ccalg': exp.get_competing_ccalg_display(),
                }
                job = django_rq.enqueue(run_experiment, inputs)
                exp.job_id = job.get_id()
                exp.save()

    return redirect('index')

def list_experiments(request):
    experiments = Experiment.objects.all().order_by('-request_date')
    return render(request, 'ccamonitor/list_experiments.html', {'experiments': experiments})



