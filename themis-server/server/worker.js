const Queues = require('./queues');
const models = require('./models');
const Experiment = models.Experiment;
const Flow = models.Flow;

Queues.downloadQueue.process(async (job, done) => {
  console.log(`Downloading ${job.data.file} ${job.data.cca} ${job.data.test} ${job.data.queueSize}`);
  const exp = await Experiment.findByPk(job.data.experimentId);
  if (exp.status !== 'In Progress') {
    exp.update({ status: 'In Progress' });
  }
  await Flow.update({ status: 'Downloading' }, { where: { id: job.data.flowId }});
  if (job.data.flowId % 2 === 1) {
    done(new Error('failed download error'));
  }
  done();
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

