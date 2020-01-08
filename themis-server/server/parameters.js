const ccas = ['BBR', 'Cubic', 'Reno'];
const tests = ['iperf-website', 'iperf16-website', 'apache-website', 'video'];
const queueSizes = [32, 64, 512];
const btlbw = 10;
const rtt = 75;
module.exports = {
  ccas: ccas,
  tests: tests,
  queueSizes: queueSizes,
  btlbw: btlbw,
  rtt: rtt
};