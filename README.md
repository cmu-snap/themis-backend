# themis-backend
Backend and testbed for the Themis project

## Classification

To classify the congestion control algorithm of websites, run `python3.6 classify_websites.py --website [website1] [file1] --website [website2] [file2]...`

### How it works
`classify_websites.py` performs the following steps for each website. All processed data for the website is stored in the directory `EXP_DIR=/tmp/data-processed/[website]-[year][month][day][time]`, e.g. `/tmp/data-processed/cca.org-20190915T103243`.
1. Runs `ccalg_predict.py`, which completes at most 12 experiments, each with a different set of network conditions. Some network conditions may be skipped.
2. Gets the predicted label for each experiment with `classify_websites.snakefile`.
3. Experiments which are marked invalid by `classify_websites.snakefile` are rerun up to 3 times. If an experiment is still marked invalid after the third run, the predicted label for the experiment is considered unknown.
4. Counts the predicted labels of the final experiments. If a label has a strict majority, the congestion control algorithm of the website is classified as the majority label. Otherwise the algorithm is classified as unknown.
5. Creates queue occupancy plots for each final experiment depicting the queue occupancy of both the experiment and the training flow of the experiment's predicted label.
6. The predicted label for the website and information about the final experiments used in the prediction are saved to `EXP_DIR/[website].results`. The plots are saved to `EXP_DIR/plots`.

The classification for a website will fail if an error is encountered when running either `ccalg_predict.py` or `classify_websites.snakefile`.

### Logging
`classify_websites.py` logs info to `/tmp/cctestbed-classify-websites.log`.

### Example output
The final results file will look something like
```
{
  "website": "capitallink.com",
  "url": "http://forums.capitallink.com/greece/2017/video/manuelides.mp4",
  "predicted_label": "unknown",
  "experiments": [
    {
      "name": "5bw-35rtt-16q-capitallink.com-20190924T101931",
      "predicted_label": "cubic",
      "mark_invalid": true,
      "closest_distance": 5.4912810000000025,
      "bw_too_low": false,
      "dist_too_high": false,
      "loss_too_high": true
    },
    {
      "name": "5bw-85rtt-64q-capitallink.com-20190924T102105",
      "predicted_label": "cubic",
      "mark_invalid": true,
      "closest_distance": 7.4138009999999985,
      "bw_too_low": false,
      "dist_too_high": false,
      "loss_too_high": true
    }
    ...
  ]
}
```
