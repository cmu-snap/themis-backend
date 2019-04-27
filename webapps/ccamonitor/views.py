from django.shortcuts import render, redirect
from ccamonitor.forms import *
from ccamonitor.models import *
from ccamonitor.ccalg_agent import *
from ccamonitor.fairness_plots_code import make_plot
from rq import get_current_job
import django_rq
import json, uuid

MAX_TRIES = 3

def index(request):
    context = {'graphs': Graph.objects.all()}
    return render(request, 'ccamonitor/home.html', context)

def check_experiment(job, exp, status):
    job.status = status
    job.save()
    exp.finished_jobs = exp.finished_jobs + 1
    exp.save()
            
    # All jobs associated with this experiment have finished
    if exp.finished_jobs == exp.job_set.all().count():
        queue = django_rq.get_queue('high')
        queue.enqueue(create_graph, {
            'website': exp.website,
            'ccalgs': exp.ccalgs,
            'exp_id': exp.exp_id,
        })

def retry_job(job, status, func, inputs, qname):
    if job.num_tries < MAX_TRIES:
        job.status = 'Q' + status
        queue = django_rq.get_queue(qname)
        rq_job = queue.enqueue(func, inputs)
        job.job_id = rq_job.get_id()
        job.save()
    else:
        check_experiment(job, job.exp, 'F' + status)

@django_rq.job
def run_experiment(inputs):
    job = Job.objects.get(job_id=get_current_job().get_id())
    job.status = 'D'
    job.num_tries = job.num_tries + 1
    job.save()
    exp = job.exp
    try:
        exp_name = run_ccalg_fairness(inputs)
        job.exp_name = exp_name
        job.status = 'QM'
        job.num_tries = 0
        job.save()
        queue = django_rq.get_queue('high')
        queue.enqueue(get_metrics, exp_name)
    except Exception as e:
        print('FAIRNESS EXCEPTION {}'.format(e))
        retry_job(job, 'D', run_experiment, inputs, 'default')

@django_rq.job('high')
def get_metrics(exp_name):
    job = Job.objects.get(exp_name=exp_name)
    job.status = 'M'
    job.num_tries = job.num_tries + 1
    job.save()
    exp = job.exp
    try:
        exp_dir = str(exp.exp_id)
        if run_fairness_snakefile(exp_name, exp_dir) == 0:
            with open('/tmp/data-websites/{}/{}.metric'.format(exp_dir, exp_name)) as json_file:
                job.metrics = json.load(json_file)
                check_experiment(job, job.exp, 'C')
        else:
            check_experiment(job, job.exp, 'FM')
    except Exception as e:
        print('SNAKEFILE EXCEPTION {}'.format(e))
        retry_job(job, 'M', get_metrics, exp_name, 'high')

@django_rq.job('high')
def create_graph(inputs):
    paths = make_plot(inputs['website'], inputs['ccalgs'], str(inputs['exp_id']))
    exp = Experiment.objects.get(exp_id=inputs['exp_id'])
    for (path, ccalg) in zip(paths, inputs['ccalgs']):
        graph = Graph.objects.create(exp=exp, competing_ccalg=ccalg)
        graph.graph.name = path
        graph.save()

def queue_experiment(request):
    QUEUE_SIZES = [32, 64, 512]
    TESTS = ['I', 'I16', 'A', 'V']
    form = ExperimentForm(request.POST)
    context = {'form': ExperimentForm()}

    if request.method == 'GET':
        return render(request, 'ccamonitor/queue.html', context)

    if form.is_valid():
        website = form.cleaned_data['website']
        file_url = form.cleaned_data['file_url']
        btlbw = form.cleaned_data['btlbw']
        if btlbw is None:
            btlbw = 10
        rtt = form.cleaned_data['rtt']
        if rtt is None:
            rtt = 75
            
        ccalgs = form.cleaned_data['ccalgs']
        exp = Experiment.objects.create(
                website=website,
                file_url=file_url,
                btlbw=btlbw,
                rtt=rtt,
                ccalgs=ccalgs)
        exp.save()

        ntwrk_conditions = [(btlbw, rtt, size) for size in QUEUE_SIZES]
        for (btlbw, rtt, size) in ntwrk_conditions:
            for ccalg in ccalgs:
                for test in TESTS:
                    job = Job.objects.create(
                            exp=exp,
                            queue_size=size,
                            test=test,
                            competing_ccalg=ccalg)
                    job.save()
                    inputs = {
                        'website': website,
                        'file_url': file_url,
                        'btlbw': btlbw,
                        'rtt': rtt,
                        'queue_size': size,
                        'test': job.get_test_display(),
                        'competing_ccalg': ccalg,
                    }
                    rq_job = django_rq.enqueue(run_experiment, inputs)
                    job.job_id = rq_job.get_id()
                    job.save()
    else:
        return render(request, 'ccamonitor/queue.html', {'form': form})

    return render(request, 'ccamonitor/submitted.html', {})

def list_jobs(request):
    jobs = Job.objects.all().order_by('-request_date')
    return render(request, 'ccamonitor/list_jobs.html', {'jobs': jobs})



