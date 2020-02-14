const Queues = require('./queues');
const { Experiment, Flow } = require('./models');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const { DATA_DIR, DATA_RAW, getScriptPath } = require('./common');

const regexName = /exp_name=(.+)\n/g;

/**
 * Queue for fairness experiments. Flows are downloaded as individual jobs.
 */
Queues.fairnessQueue.process(async (job, done) => {
  console.log(`[DOWNLOADING FAIRNESS] ${job.data.website} ${job.data.file} ${job.data.queueSize} ${job.data.test} ${job.data.cca}...`)

  const exp = await Experiment.findByPk(job.data.experimentId);
  if (exp.status !== 'In Progress') {
    await exp.update({ status: 'In Progress' });
  }
  await Flow.update({ status: 'Downloading' }, { where: { id: job.data.flowId }});
  
  const ccalgFairness = getScriptPath('ccalg_fairness.py');
  const website = `--website ${job.data.website} ${job.data.file}`;
  const network = `--network ${job.data.btlbw} ${job.data.rtt} ${job.data.queueSize}`;
  const test = `--test ${job.data.test} --competing_ccalg ${job.data.cca.toLowerCase()}`;
  const args = `${ccalgFairness} ${website} ${network} ${test} --num_competing 1 --duration 240`;
  const child = spawn('python3.6', args.split(' '));

  let output = '';
  let error = '';

  child.on('error', (err) => {
    console.error('Failed to start subprocess');
    done(new Error(err));
  });

  child.stdout.on('data', (data) => {
    console.log(data.toString());
    output += data.toString();
  });

  child.stderr.on('data', (data) => { error += data.toString(); });

  child.on('close', (code) => {
    if (code === 0) {
      const matches = output.match(regexName)
      if (matches.length >= 2) {
        done(null, { name: matches[1] });
      } else {
        done(new Error('Failed to get fairness flow name'));
      }
    } else {
      console.error(error);
      done(new Error(error));
    }
  });
});

/**
 * Queue for classification experiments. The initial job for a classification
 * experiment runs all flows at once. Individual flows which are marked invalid
 * will be re-downloaded as individual jobs and the flowId field will be in job.data.
 */
Queues.classifyQueue.process(async (job, done) => {
  console.log(`[DOWNLOADING CLASSIFICATION] ${job.data.website} ${job.data.file} ${job.data.btlbw} ${job.data.rtt} ${job.data.tries}...`)

  const exp = await Experiment.findByPk(job.data.experimentId);
  if (exp.status !== 'In Progress') {
    await exp.update({ status: 'In Progress' });
  }

  if (job.data.flowId) {
    await Flow.update({ status: 'Downloading' }, { where: { id: job.data.flowId }});
  }
  
  const ccalgPredict = getScriptPath('ccalg_predict.py');
  const website = `--website ${job.data.website} ${job.data.file}`;
  const network = job.data.flowId ? `--network ${job.data.btlbw} ${job.data.rtt}` : '';
  const args = `${ccalgPredict} ${website} ${network}`;
  const child = spawn('python3.6', args.split(' '));

  let output = '';
  let error = '';

  child.on('error', (err) => {
    console.error('Failed to start subprocess');
    done(new Error(err));
  });

  child.stdout.on('data', (data) => {
    console.log(data.toString());
    output += data.toString();
  });

  child.stderr.on('data', (data) => { error += data.toString(); });

  child.on('close', (code) => {
    if (code === 0) {
      const matches = output.matchAll(regexName);
      const names = [];
      for (const match of matches) {
        if (fs.existsSync(`${DATA_RAW}/${match[1]}.tar.gz`)) {
          names.push(match[1]);
        }
      }
      if (names.length > 0) {
        done(null, { names: names });
      } else {
        done(new Error('Unable to get flows for website'));
      }
    } else {
      console.error(error);
      done(new Error(error));
    }
  });
});

/**
 * Queue for analyzing flow data. Runs the appropriate snakefile for the 
 * experiment type.
 */
Queues.analysisQueue.process(async (job, done) => {
  console.log(`[ANALYZING] ${job.data.name}`);
  await Flow.update({ status: 'Analyzing data' }, { where: { id: job.data.flowId }});
  const exp = await Experiment.findByPk(experimentId);
  if (!exp.directory) {
    await exp.update({ directory: `${job.data.website}-${job.data.experimentId}`});
  }
  await fs.promises.mkdir(path.join(DATA_DIR, exp.directory), { recursive: true });
  
  let args = '';
  const resultsDir = path.join('data-websites', exp.directory);
  if (job.data.type === 'Classification') {
    const snakefile = getScriptPath('classify_websites.snakefile');
    args = `--config exp_name=${job.data.name} results_dir=${resultsDir} -s ${snakefile} --latency-wait 10`;
  } else {
    const snakefile = getScriptPath('fairness_websites.snakefile');
    args = `--config exp_name=${job.data.name} metric_dir="${resultsDir}" -s ${snakefile}`;
  }
  const child = spawn('snakemake', args.split(' '));

  let error = '';

  child.on('error', (err) => {
    console.error('Failed to start subprocess');
    done(new Error(err));
  });

  child.stdout.on('data', (data) => {
    console.log(data.toString());
  });

  child.stderr.on('data', (data) => { error += data.toString(); });

  child.on('close', (code) => {
    if (code === 0) {
      const resultsPath = path.join(DATA_DIR, exp.directory, `${job.data.name}.results`);
      fs.readFile(resultsPath, (err, results) => {
        if (err) {
          console.error(err);
          done(new Error(err));
        } else if (job.data.type === 'Classification') {
          const label = results['mark_invalid'] ? 'invalid' : results['predicted_label'];
          Flow
            .update({ results: results, label: label }, { where: { id: job.data.flowId }})
            .then(_ => done(null, { isInvalid: results['mark_invalid'] }));
        } else {
          Flow
            .update({ results: results}, { where: { id: job.data.flowId }})
            .then(_ => done());
        }
      }); 
    } else {
      console.error(error);
      done(new Error(error));
    }
  });
});

Queues.plotQueue.process(async (job, done) => {
  console.log(`[PLOTTING RESULTS] experiment ${job.data.experimentId}`);

  if (job.data.type === 'Fairness') {
    const fairnessPlots = getScriptPath('fairness_plots_code.py');
    const ccas = job.data.ccas.join(' ');
    const args = `${fairnessPlots} --website ${job.data.website} --ccas ${ccas} --exp_dir ${job.data.expDir}`;
    const child = spawn('python3.6', args.split(' '));
  
    let error = '';
    let output = '';
  
    child.on('error', (err) => {
      console.error('Failed to start subprocess');
      done(new Error(err));
    });
  
    child.stdout.on('data', (data) => {
      console.log(data.toString());
      output += data.toString();
    });
  
    child.stderr.on('data', (data) => { error += data.toString(); });
  
    child.on('close', (code) => {
      if (code === 0) {
        done(null, { plots: output.trim().split(' ') });
      } else {
        console.error(error);
        done(new Error(error));
      }
    });
  } else {
    
  }
});

if (process.argv.length > 2) {
  if (process.argv[2] === 'pause') {
    Queues.fairnessQueue.pause().then(() => Queues.classifyQueue.pause())
    .then(() => Queues.analysisQueue.pause())
    .then(() => Queues.plotQueue.pause())
    .then(() => console.log('[PAUSED QUEUES]'))
    .catch(err => console.error(err));
  } else if (process.argv[2] === 'resume') {
    Queues.fairnessQueue.resume().then(() => Queues.classifyQueue.resume())
    .then(() => Queues.analysisQueue.resume())
    .then(() => Queues.plotQueue.resume())
    .then(() => console.log('[RESUMED QUEUES]'))
    .catch(err => console.error(err));
  }
}

