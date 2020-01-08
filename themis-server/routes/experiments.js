const Queues = require('../server/queues.js');
const models = require('../server/models');
const Experiment = models.Experiment;
const Flow = models.Flow;
const params = require('../server/parameters');
const express = require('express');
const router = express.Router();

router.get('/', function(req, res, next) {
  if (req.params.id) {
    next();
  } else {
    res.send('API is working properly');
  }
});

router.post('/submit', async (req, res, next) => {
  try {
    const exp = await Experiment.create({
      website: req.body.website,
      file: req.body.file,
      email: req.body.email,
      ccas: req.body.ccas
    });
    console.log(`Created experiment with id ${exp.id}`);
    const totalFlows = params.queueSizes.length * exp.ccas.length * params.tests.length;
    for (const queueSize of params.queueSizes) {
      for (const cca of exp.ccas) {
        for (const test of params.tests) {
          let fields = {
            btlbw: params.btlbw,
            rtt: params.rtt,
            queueSize: queueSize,
            cca: cca,
            test: test,
            experimentId: exp.id
          };
          const flow = await Flow.create(fields);
          fields['flowId'] = flow.id;
          fields['website'] = exp.website;
          fields['file'] = exp.file;
          fields['totalFlows'] = totalFlows;
          Queues.downloadQueue.add(fields, Queues.jobOptions);
        }
      }
    }
    res.send('Experiment submitted');
  } catch (err) {
    next(err);
  }
});

router.get('/:id', function(req, res, next) {
  console.log(`Get experiment with id ${req.params.id}`);
  res.send(`Get experiment with id ${req.params.id}`);
});

module.exports = router;