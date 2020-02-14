const glob = require('glob');
const fs = require('fs');

const DATA_DIR = path.join(path.sep, 'tmp', 'data-websites');
const DATA_RAW = path.join(path.sep, 'tmp', 'data-raw');
const DATA_TMP = path.join(path.sep, 'tmp', 'data-tmp');

/**
 * Return path to the given script. Expects the script to be relative to the base
 * directory of the themis-backend repo.
 * @param {string} script 
 */
function getScriptPath(script) {
  const pathList = __dirname.split(path.sep);
  pathList.pop();
  pathList.pop();
  return path.join(path.sep, ...pathList, script);
}

/**
 * Parse the network conditions from an experiment name.
 * @param {string} expName
 */ 
function parseNetwork(expName) {
  const bw = /^(\d+)bw/;
  const rtt = /^\d+bw-(\d+)rtt/;
  const bwMatch = expName.match(bw);
  const rttMatch = expName.match(rtt);
  if (bwMatch.length > 0 && rttMatch.length > 0) {
    return [bwMatch[1], rttMatch[1]];
  }
  return [];
}

/**
 * Remove all files prefixed with the given experiment name.
 * @param {string} expName
 * @param {string} expDir
 */
function removeExperiment(expName, expDir) {
  if (!expName) return;

  let directories = [DATA_RAW, DATA_TMP, '/tmp'];
  if (expDir) {
    directories.push(expDir);
  }
  const patterns = directories.map(dir => `${dir}/${expName}*`);
  for (const pattern of patterns) {
    glob(pattern, (err, files) => {
      files.forEach(file => {
        fs.unlink(filepath, err => {
          if (err) {
            console.error(err);
            return;
          }
        });
      });
    });
  }
}

module.exports = {
  DATA_DIR: DATA_DIR,
  DATA_RAW: DATA_RAW,
  getScriptPath: getScriptPath,
  parseNetwork: parseNetwork,
  removeExperiment: removeExperiment,
};