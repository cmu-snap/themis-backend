const Queues = require('./queues');

Queues.experimentQueue.process(function(job, done) {
  console.log(`Processing job ${job.id} website ${job.data.website} ${job.data.file}`);
  done();
});

