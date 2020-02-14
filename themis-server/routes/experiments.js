const Queues = require('../server/queues.js');
const { Experiment, Flow } = require('../server/models');
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
    const experimentType = req.body.experimentType.charAt(0).toUpperCase() + req.body.experimentType.slice(1);
    const exp = await Experiment.create({
      website: req.body.website,
      file: req.body.file,
      email: req.body.email,
      ccas: req.body.ccas,
      experimentType: experimentType
    });

    if (experimentType === 'Fairness') {
      const totalFlows = params.queueSizes.length * exp.ccas.length * params.tests.length;
      for (const queueSize of params.queueSizes) {
        for (const cca of exp.ccas) {
          for (const test of Object.keys(params.tests)) {
            let fields = {
              btlbw: params.tests[test].btlbw,
              rtt: params.tests[test].rtt,
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
            Queues.fairnessQueue.add(fields, Queues.jobOptions);
          }
        }
      }
    } else {
      Queues.classifyQueue.add({
        website: exp.website,
        file: exp.file,
        btlbw: null,
        rtt: null,
        flowId: null,
        experimentId: exp.id,
        tries: 1
      }, Queues.jobOptions);
    }
    res.send('Experiment submitted');
  } catch (err) {
    console.error(err);
    next(err);
  }
});

router.get('/:id', function(req, res, next) {
  console.log(`Get experiment with id ${req.params.id}`);
  res.send(`Get experiment with id ${req.params.id}`);
});

module.exports = router;
