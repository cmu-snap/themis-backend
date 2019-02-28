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
    returncode = run_ccalg_fairness(inputs)
    print('RETURN CODE {}'.format(returncode))
    #print('Successfully ran experiment! tar={} name={}'.format(tar, name))

def queue_experiment(request):
    form = ExperimentForm(request.POST)
    context = {'form': ExperimentForm()}

    if form.is_valid():
        website = form.cleaned_data['website']
        filename = form.cleaned_data['filename']
        btlbw = form.cleaned_data['btlbw']
        rtt = form.cleaned_data['rtt']
        queue_size = form.cleaned_data['queue_size']
        
        if None in [btlbw, rtt, queue_size]:
            ntwrk_conditions = [(10, 75, 32)]
            #ntwrk_conditions = [(10, 75, 32), (10, 75, 64), (10, 75, 512)]
        else:
            ntwrk_conditions = [(btlbw, rtt, queue_size)]

        tests = ['iperf-website']
        competing_ccalgs = ['cubic']

        for (btlbw, rtt, queue_size) in ntwrk_conditions:
            for test in tests:
                for ccalg in competing_ccalgs:
                    inputs = {
                        'website': website,
                        'filename': filename,
                        'btlbw': btlbw,
                        'rtt': rtt,
                        'queue_size': queue_size,
                        'test': test,
                        'competing_ccalg': ccalg
                    }
                    job = django_rq.enqueue(run_experiment, inputs)
                    # TODO: use job.get_id() to create instance of job model

    return redirect('index')


