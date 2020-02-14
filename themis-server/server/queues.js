const Queue = require('bull');
const { Experiment, Flow } = require('./models');
const { Op } = require('sequelize');
const { parseNetwork, removeExperiment } = require('./common');

// Define job queues for downloading website files, analyzing experiment data, and plotting.
const fairnessQueue = new Queue('download fairness files', process.env.REDIS_URL);
const classificationQueue = new Queue('download classification files', process.env.REDIS_URL);
const analysisQueue = new Queue('analyze experiment data', process.env.REDIS_URL);
const plotQueue = new Queue('plot results', process.env.REDIS_URL);

const jobOptions = { attempts: 3 }; // number of times to retry failed job
const RETRY_INVALID_LIMIT = 3; // number of times to re-download invalid classification flow

async function updateFlow(flowStatus, data) {
  await Flow.update({ status: flowStatus }, { where: { id: data.flowId }});
  await isExperimentFinished(data.experimentId);
}

/**
 * Checks if all of the flows associated with the given experiment are finished.
 * If they are, pushes the experiment onto the plot queue.
 * @param {string} experimentId 
 */
async function isExperimentFinished(experimentId) {
  const totalFlows = await Flow.count({ where: { experimentId: experimentId }});
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
    const fields = {
      experimentId: experimentId,
      expDir: exp.directory,
      ccas: exp.ccas,
      website: exp.website,
      type: exp.experimentType
    };
    // Plot fairness experiment if at least half the flows completed, and plot
    // classification experiment if all flows were successfully classified.
    if ((exp.experimentType === 'Fairness' && failedFlows < finishedFlows / 2 && exp.directory) ||
        (exp.experimentType === 'Classification' && finishedFlows === totalFlows && failedFlows === 0)) {
      plotQueue.add(fields, { attempts: 1 });
    } else {
      await exp.update({ status: 'Failed' });
      console.log(`[EXPERIMENT FAILED] experiment ${experimentId}`);
    }
  }
}

/**
 * Fairness queue. Downloaded flows are pushed onto the analysis queue to process
 * the data and create metrics files. Failed downloads are retried up to 3 times.
 */
fairnessQueue.on('completed', async (job, result) => {
  console.log(`[FAIRNESS DOWNLOAD COMPLETE] flow ${job.data.flowId} result ${result.name}`);
  await Flow.update({ name: result.name, status: 'Queued for analysis' }, { where: { id: job.data.flowId }});
  analysisQueue.add({
    name: result.name,
    flowId: job.data.flowId,
    experimentId: job.data.experimentId,
    website: job.data.website,
    file: job.data.file,
    tries: 1,
    type: 'Fairness',
  }, jobOptions);
})
.on('failed', async (job, err) => {
  console.log(`[FAIRNESS DOWNLOAD FAILED] flow ${job.data.flowId} tries ${job.attemptsMade}`);
  if (job.attemptsMade === jobOptions.attempts) {
    await updateFlow('Failed download', job.data);
  }
})
.on('stalled', function (job) {
  console.log(`[FAIRNESS DOWNLOAD STALLED] flow ${job.data.flowId} stalled`); 
});

/**
 * Classification queue. Completed flows are pushed onto the analysis queue to
 * classify the flow. Failed downloads are retried up to 3 times.
 */
classificationQueue.on('completed', async (job, result) => {
  console.log(`[CLASSIFICATION DOWNLOAD COMPLETE] result ${result.names}`);
  const flowIds = [];
  if (job.data.flowId) {
    // Delete data from previous download.
    const exp = await Experiment.findByPk(job.data.experimentId);
    const flow = await Flow.findByPk(job.data.flowId);
    removeExperiment(flow.name, exp.directory);
    
    // Update flow with new name and status.
    flow.name = result.names[0];
    flow.status = 'Queued for analysis';
    flow.save();
    flowIds.push(job.data.flowId);
  } else {
    for (const name of result.names) {
      const network = parseNetwork(name);
      const flow = await Flow.create({
        btlbw: network[0],
        rtt: network[1],
        experimentId: job.data.experimentId,
        status: 'Queued for analysis',
        name: name
      });
      flowIds.push(flow.id);
    }
  }
  for (const id of flowIds) {
    analysisQueue.add({
      name: name,
      flowId: id,
      experimentId: job.data.experimentId,
      website: job.data.website,
      file: job.data.file,
      tries: job.data.tries,
      type: 'Classification'
    }, jobOptions);
  }
})
.on('failed', async (job, err) => {
  console.log(`[CLASSIFICATION DOWNLOAD FAILED] flow ${job.data.flowId} tries ${job.attemptsMade}`);
  if (job.attemptsMade === jobOptions.attempts && !job.data.flowId) {
    await Experiment.update({ status: 'Failed' }, { where: { id: job.data.experimentId }});
  } else {
    await updateFlow('Failed download', job.data);
  }
})
.on('stalled', function (job) {
  console.log(`[CLASSIFICATION DOWNLOAD STALLED] flow ${job.data.flowId} stalled`); 
});

/**
 * Analysis queue. If a classification flow completed classification but was
 * marked as invalid, re-downloads the flow up to RETRY_INVALID_LIMIT times.
 * Failed analysis jobs are retried up to 3 times.
 */
analysisQueue.on('completed', async (job, result) => {
  console.log(`[ANALYSIS COMPLETE] flow ${job.data.flowId}`);
  // Classification flow was marked as invalid, so add the flow to the download queue.
  if (job.data.type === 'Classification' && result.isInvalid && job.data.tries < RETRY_INVALID_LIMIT) {
    const flow = await Flow.findByPk(job.data.flowId);
    flow.status = 'Queued for download';
    flow.save();
    classificationQueue.add({
      website: job.data.website,
      file: job.data.file,
      btlbw: flow.btlbw,
      rtt: flow.rtt,
      flowId: flow.id,
      experimentId: job.data.experimentId,
      tries: job.data.tries + 1
    }, jobOptions);
  } else {
    await updateFlow('Completed', job.data);
  }
})
.on('failed', async (job, err) => {
  console.log(`[ANALYSIS FAILED] flow ${job.data.flowId} tries ${job.attemptsMade} failed`);
  if (job.attemptsMade === jobOptions.attempts) {
    await updateFlow('Failed analysis', job.data);
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
  fairnessQueue: fairnessQueue,
  classificationQueue: classificationQueue,
  analysisQueue: analysisQueue,
  plotQueue: plotQueue,
  jobOptions: jobOptions
};
