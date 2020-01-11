const Queue = require('bull');
const { Experiment, Flow } = require('./models');
const { Op } = require('sequelize');

const downloadQueue = new Queue('download files', process.env.REDIS_URL);
const metricsQueue = new Queue('process metrics', process.env.REDIS_URL);
const plotQueue = new Queue('plot results', process.env.REDIS_URL);

const jobOptions = { attempts: 3 };

async function updateFlow(flowStatus, data) {
  await Flow.update({ status: flowStatus }, { where: { id: data.flowId }});
  await plotExperiment(data.experimentId, data.totalFlows);
}

/**
 * Plots the experiment with the given id if all of its associated flows are finished.
 * @param {string} experimentId 
 */
async function plotExperiment(experimentId, totalFlows) {
  const finishedFlows = await Flow.count({ where: { experimentId: experimentId, isFinished: true }});
  const failedFlows = await Flow.count({
    where: {
      experimentId: experimentId,
      isFinished: true,
      status: {
        [Op.ne]: 'Completed'
      }
    }
  });

  if (totalFlows === finishedFlows) {
    const exp = await Experiment.findByPk(experimentId);
    // Plot results if at least half the flows completed
    if (failedFlows < finishedFlows / 2 && exp.directory) {
      plotQueue.add({
        experimentId: experimentId,
        ccas: exp.ccas,
        expDir: exp.directory,
        website: exp.website
      }, { attempts: 1 });
    } else {
      await exp.update({ status: 'Failed' });
      console.log(`[EXPERIMENT FAILED] experiment ${experimentId}`);
    }
  }
}

downloadQueue.on('completed', async (job, result) => {
  console.log(`[DOWNLOAD COMPLETE] flow ${job.data.flowId} result ${result.name}`);
  await Flow.update({ name: result.name, status: 'Queued for metrics' }, { where: { id: job.data.flowId }});
  metricsQueue.add({
    name: result.name,
    flowId: job.data.flowId,
    experimentId: job.data.experimentId,
    website: job.data.website,
  }, jobOptions);
})
.on('failed', async (job, err) => {
  console.log(`[DOWNLOAD FAILED] flow ${job.data.flowId} tries ${job.attemptsMade}`);
  if (job.attemptsMade === jobOptions.attempts) {
    await updateFlow('Failed download', job.data);
  }
})
.on('stalled', function (job) {
  console.log(`[DOWNLOAD STALLED] flow ${job.data.flowId} stalled`); 
});

metricsQueue.on('completed', async (job, result) => {
  console.log(`[METRICS COMPLETE] flow ${job.data.flowId}`);
  await updateFlow('Completed', job.data);
})
.on('failed', async (job, err) => {
  console.log(`[METRICS FAILED] flow ${job.data.flowId} tries ${job.attemptsMade} failed`);
  if (job.attemptsMade === jobOptions.attempts) {
    await updateFlow('Failed to get metrics', job.data);
  }
});

plotQueue.on('completed', async (job, result) => {
  console.log(`[PLOT COMPLETE] experiment ${job.data.experimentId} completed`);
  await Experiment.update({ status: 'Completed' }, { where: { id: job.data.experimentId }});
})
.on('failed', async (job, err) => {
  console.log(`[PLOT FAILED] experiment ${job.data.experimentId} failed`);
  await Experiment.update({ status: 'Failed' }, { where: { id: job.data.experimentId }});
})

module.exports = {
  downloadQueue: downloadQueue,
  metricsQueue: metricsQueue,
  plotQueue: plotQueue,
  jobOptions: jobOptions
};
