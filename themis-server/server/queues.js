const Queue = require('bull');

const experimentQueue = new Queue('run experiments', process.env.REDIS_URL);
experimentQueue.on('completed', function(job, result) {
  console.log(`Completed job ${job.id}`);
});

const jobOptions = { attempts: 3 };

module.exports = { experimentQueue: experimentQueue, jobOptions: jobOptions };