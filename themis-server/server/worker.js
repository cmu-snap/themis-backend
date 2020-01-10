const Queues = require('./queues');
const { Experiment, Flow } = require('./models');
const { exec } = require('child_process');

Queues.downloadQueue.process(async (job, done) => {
  const exp = await Experiment.findByPk(job.data.experimentId);
  if (exp.status !== 'In Progress') {
    exp.update({ status: 'In Progress' });
  }
  await Flow.update({ status: 'Downloading' }, { where: { id: job.data.flowId }});
  const website = `--website ${job.data.website} ${job.data.file}`
  const network = `--network ${job.data.btlbw} ${job.data.rtt} ${job.data.queueSize}`
  const test = `--test ${job.data.test} --competing_ccalg ${job.data.cca}`
  const cmd = `python3 ~/git/meganyu/ccalg_fairness.py ${website} ${network} ${test} --num_competing 1 --duration 240`
  exec(cmd, (err, stdout, stderr) => {
    if (err) {
      console.error(`exec error: ${err}`);
      done(new Error(err));
    } else if (stderr) {
      done(new Error(stderr));
    } else {
      const regexName = /exp_name=(.+)\n/
      const matches = stdout.match(regexName)
      if (matches.length >= 2) {
        done(matches[1]);
      } else {
        done('');
      }
    }
  });
});

Queues.metricsQueue.process(async (job, done) => {
  console.log(`Processing metrics ${job.data.name}`);
  await Flow.update({ status: 'Processing metrics' }, { where: { id: job.data.flowId }});
  if (job.data.flowId % 4 === 0) {
    done(new Error('failed metrics error'));
  }
  done();
});

Queues.plotQueue.process(async (job, done) => {
  console.log(`Creating plot for experiment ${job.experimentId}`);
  done();
});

