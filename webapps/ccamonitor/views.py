from django.shortcuts import render, redirect
from ccamonitor.forms import *
from ccamonitor.ccalg_agent import *
from rq import get_current_job
import django_rq

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
        exp.status = 'C'
        exp.exp_name = exp_name
        print('Successfully ran experiment! exp_name={}'.format(exp_name))
    except Exception as e:
        print('Experiment failed.')
        exp.status = 'F'
    exp.save()

def queue_experiment(request):
    QUEUE_SIZES = [32, 64, 512]
    form = ExperimentForm(request.POST)
    context = {'form': ExperimentForm()}

    if form.is_valid():
        website = form.cleaned_data['website']
        filename = form.cleaned_data['filename']
        btlbw = form.cleaned_data['btlbw']
        rtt = form.cleaned_data['rtt']
        queue_size = form.cleaned_data['queue_size']
        test = form.cleaned_data['test']
        competing_ccalg = form.cleaned_data['competing_ccalg']

        ntwrk_conditions = [(btlbw, rtt, queue_size)]
        # If queue_size unspecified, run once for each size in QUEUE_SIZES
        if queue_size is None:
            ntwrk_conditions = [(btlbw, rtt, size) for size in QUEUE_SIZES]

        ccalgs = [competing_ccalg]
        if competing_ccalg == '':
            ccalgs = ['C', 'B', 'R']

        for (btlbw, rtt, size) in ntwrk_conditions:
            for ccalg in ccalgs:
                exp = Experiment.objects.create(
                        website=website,
                        filename=filename,
                        btlbw=btlbw,
                        rtt=rtt,
                        queue_size=size,
                        test=test,
                        competing_ccalg=ccalg
                        )
                inputs = {
                    'website': website,
                    'filename': filename,
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
    experiments = Experiment.objects.all()
    return render(request, 'ccamonitor/list_experiments.html', {'experiments': experiments})



