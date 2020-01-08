const Queue = require('bull');
const models = require('./models');
const Experiment = models.Experiment;
const Flow = models.Flow;

const downloadQueue = new Queue('download files', process.env.REDIS_URL);
const metricsQueue = new Queue('process metrics', process.env.REDIS_URL);
const plotQueue = new Queue('plot results', process.env.REDIS_URL);

const jobOptions = { attempts: 3 };

/**
 * Plots the experiment with the given id if all of its associated flows are finished.
 * @param {string} experimentId 
 */
async function plotExperiment(experimentId, totalFlows) {
  const finishedFlows = await Flow.count({ where: { experimentId: experimentId, isFinished: true }});
  if (totalFlows === finishedFlows) {
    const exp = await Experiment.findByPk(experimentId);
    plotQueue.add({ experimentId: experimentId, ccas: exp.ccas, website: exp.website }, { attempts: 1 });
  }
}

downloadQueue.on('completed', async (job, result) => {
  console.log(`Completed download for flow ${job.data.flowId}`);
  const name = 'placeholder';
  await Flow.update({ name: name, status: 'Queued for metrics' }, { where: { id: job.data.flowId }});
  metricsQueue.add({ name: name, flowId: job.data.flowId }, jobOptions);
})
.on('failed', async (job, err) => {
  console.log(`Download flow ${job.data.flowId} tries ${job.attemptsMade} failed with error ${err}`);
  if (job.attemptsMade === jobOptions.attempts) {
    await Flow.update({ status: 'Failed download' }, { where: { id: job.data.flowId }});
    await plotExperiment(job.data.experimentId, job.data.totalFlows);
  }
});

metricsQueue.on('completed', async (job, result) => {
  console.log(`Completed metrics for flow ${job.data.flowId}`);
  await Flow.update({ status: 'Completed' }, { where: { id: job.data.flowId }});
  await plotExperiment(job.data.experimentId, job.data.totalFlows);
})
.on('failed', async (job, err) => {
  console.log(`Metrics flow ${job.data.flowId} tries ${job.attemptsMade} failed with error ${err}`);
  if (job.attemptsMade === jobOptions.attempts) {
    await Flow.update({ status: 'Failed to get metrics' }, { where: { id: job.data.flowId }});
    await plotExperiment(job.data.experimentId, job.data.totalFlows);
  }
});

plotQueue.on('completed', async (job, result) => {
  console.log(`Plotted results for experiment ${job.data.experimentId}`);
  await Experiment.update({ status: 'Completed' }, { where: { id: job.data.experimentId }});
})
.on('failed', async (job, err) => {
  console.log(`Plot experiment ${job.data.experimentId} failed with error ${err}`);
  await Experiment.update({ status: 'Failed' }, { where: { id: job.data.experimentId }});
})

module.exports = {
  downloadQueue: downloadQueue,
  metricsQueue: metricsQueue,
  plotQueue: plotQueue,
  jobOptions: jobOptions
};