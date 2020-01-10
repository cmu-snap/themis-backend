const Queues = require('./queues');
const { Experiment, Flow } = require('./models');
const { spawn } = require('child_process');

Queues.downloadQueue.process(async (job, done) => {
  console.log(`Downloading ${job.data.website} ${job.data.file} ${job.data.queueSize} ${job.data.test} ${job.data.cca}...`)
  const exp = await Experiment.findByPk(job.data.experimentId);
  if (exp.status !== 'In Progress') {
    await exp.update({ status: 'In Progress' });
  }
  await Flow.update({ status: 'Downloading' }, { where: { id: job.data.flowId }});
  
  const website = `--website ${job.data.website} ${job.data.file}`
  const network = `--network ${job.data.btlbw} ${job.data.rtt} ${job.data.queueSize}`
  const test = `--test ${job.data.test} --competing_ccalg ${job.data.cca.toLowerCase()}`
  const args = `/opt/cctestbed/ccalg_fairness.py ${website} ${network} ${test} --num_competing 1 --duration 240`
  const child = spawn('python3.6', args.split(' '), { stdio: ['inherit', 'pipe', 'pipe'] });

  let output = '';
  let error = '';

  child.on('error', (err) => {
    console.error('Failed to start subprocess');
    done(new Error(err));
  });

  child.stdout.on('data', (data) => { output += data; });

  child.stderr.on('data', (data) => { error += data; });

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
  console.log(`Processing metrics ${job.data.name}`);
  await Flow.update({ status: 'Processing metrics' }, { where: { id: job.data.flowId }});
  done();
});

Queues.plotQueue.process(async (job, done) => {
  console.log(`Creating plot for experiment ${job.data.experimentId}`);
  done();
});

