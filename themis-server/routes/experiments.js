const Queues = require('../server/queues.js');
const express = require('express');
const router = express.Router();

router.get('/', function(req, res, next) {
  if (req.params.id) {
    next();
  } else {
    res.send('API is working properly');
  }
});

router.post('/submit', function(req, res, next) {
  console.log(req.body);
  Queues.experimentQueue.add(req.body, Queues.jobOptions);
  res.send('Experiment submitted');
});

router.get('/:id', function(req, res, next) {
  console.log(`Get experiment with id ${req.params.id}`);
  res.send(`Get experiment with id ${req.params.id}`);
});

module.exports = router;