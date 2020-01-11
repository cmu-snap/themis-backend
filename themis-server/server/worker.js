const Queues = require('./queues');
const { Experiment, Flow } = require('./models');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(path.sep, 'tmp', 'data-websites');

Queues.downloadQueue.process(async (job, done) => {
  console.log(`[DOWNLOADING] ${job.data.website} ${job.data.file} ${job.data.queueSize} ${job.data.test} ${job.data.cca}...`)

  const exp = await Experiment.findByPk(job.data.experimentId);
  if (exp.status !== 'In Progress') {
    await exp.update({ status: 'In Progress' });
  }
  await Flow.update({ status: 'Downloading' }, { where: { id: job.data.flowId }});
  
  const pathList = __dirname.split(path.sep);
  pathList.pop();
  pathList.pop();
  const ccalgFairness = path.join(path.sep, ...pathList, 'ccalg_fairness.py');

  const website = `--website ${job.data.website} ${job.data.file}`;
  const network = `--network ${job.data.btlbw} ${job.data.rtt} ${job.data.queueSize}`;
  const test = `--test ${job.data.test} --competing_ccalg ${job.data.cca.toLowerCase()}`;
  const args = `${ccalgFairness} ${website} ${network} ${test} --num_competing 1 --duration 240`;
  const child = spawn('python3.6', args.split(' '));

  let output = '';
  let error = '';

  child.on('error', (err) => {
    console.error('Failed to start subprocess');
    done(new Error(err));
  });

  child.stdout.on('data', (data) => {
    console.log(data.toString());
    output += data.toString();
  });

  child.stderr.on('data', (data) => { error += data.toString(); });

  child.on('close', (code) => {
    if (code === 0) {
      const regexName = /exp_name=(.+)\n/
      const matches = output.match(regexName)
      if (matches.length >= 2) {
        done(null, { name: matches[1] });
      } else {
        done(new Error('Failed to get experiment name'));
      }
    } else {
      console.error(error);
      done(new Error(error));
    }
  });
});

Queues.metricsQueue.process(async (job, done) => {
  console.log(`[PROCESSING METRICS] ${job.data.name}`);
  await Flow.update({ status: 'Processing metrics' }, { where: { id: job.data.flowId }});
  const exp = await Experiment.findByPk(experimentId);
  if (!exp.directory) {
    await exp.update({ directory: `${job.data.website}-${job.data.experimentId}`});
  }
  await fs.promises.mkdir(path.join(DATA_DIR, exp.directory), { recursive: true });
    
  const pathList = __dirname.split(path.sep);
  pathList.pop();
  pathList.pop();
  const snakefile = path.join(path.sep, ...pathList, 'fairness_websites.snakefile');
  const metricDir = path.join('data-websites', exp.directory);
  const args = `--config exp_name=${job.data.name} metric_dir="${metricDir}" -s ${snakefile}`;
  const child = spawn('snakemake', args.split(' '));

  let error = '';

  child.on('error', (err) => {
    console.error('Failed to start subprocess');
    done(new Error(err));
  });

  child.stdout.on('data', (data) => {
    console.log(data.toString());
  });

  child.stderr.on('data', (data) => { error += data.toString(); });

  child.on('close', (code) => {
    if (code === 0) {
      const metricsPath = path.join(DATA_DIR, exp.directory, `${job.data.name}.metric`);
      fs.readFile(metricsPath, (err, metrics) => {
        if (err) {
          console.error(err);
          done(new Error(err));
        } else {
          Flow
            .update({ metrics: metrics }, { where: { id: job.data.flowId }})
            .then(_ => done());
        }
      }); 
    } else {
      console.error(error);
      done(new Error(error));
    }
  });
});

Queues.plotQueue.process(async (job, done) => {
  console.log(`[PLOTTING RESULTS] experiment ${job.data.experimentId}`);

  const pathList = __dirname.split(path.sep);
  pathList.pop();
  pathList.pop();
  const fairnessPlots = path.join(path.sep, ...pathList, 'fairness_plots_code.py');
  const ccas = job.data.ccas.join(' ');
  const args = `${fairnessPlots} --website ${job.data.website} --ccas ${ccas} --exp_dir ${job.data.expDir}`;
  const child = spawn('python3.6', args.split(' '));

  let error = '';
  let output = '';

  child.on('error', (err) => {
    console.error('Failed to start subprocess');
    done(new Error(err));
  });

  child.stdout.on('data', (data) => {
    console.log(data.toString());
    output += data.toString();
  });

  child.stderr.on('data', (data) => { error += data.toString(); });

  child.on('close', (code) => {
    if (code === 0) {
      done(null, { plots: output.trim().split(' ') });
    } else {
      console.error(error);
      done(new Error(error));
    }
  });
});

if (process.argv.length > 2) {
  if (process.argv[2] === 'pause') {
    Queues.downloadQueue.pause().then(() => Queues.metricsQueue.pause())
    .then(() => Queues.plotQueue.pause())
    .then(() => console.log('[PAUSED QUEUES]'))
    .catch(err => console.error(err));
  } else if (process.argv[2] === 'resume') {
    Queues.downloadQueue.resume().then(() => Queues.metricsQueue.resume())
    .then(() => Queues.plotQueue.resume())
    .then(() => console.log('[RESUMED QUEUES]'))
    .catch(err => console.error(err));
  }
}

