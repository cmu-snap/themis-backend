const ccas = ['BBR', 'Cubic', 'Reno'];
const tests = {
  'iperf-website': { btlbw: 10, rtt: 75 },
  'iperf16-website': { btlbw: 10, rtt: 75 },
  'apache-website': { btlbw: 10, rtt: 75 },
  'video': { btlbw: 5, rtt: 75 }
};
const queueSizes = [32, 64, 512];
module.exports = {
  ccas: ccas,
  tests: tests,
  queueSizes: queueSizes,
};