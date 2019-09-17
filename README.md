## Classification

To classify the congestion control algorithm of websites, run `python3.6 classify_websites.py --website [website1] [file1] --website [website2] [file2]...`

### How it works
`classify_websites.py` performs the following steps for each website:
1. Runs `ccalg_predict.py`, which completes at most 12 experiments, each with a different set of network conditions. Some network conditions may be skipped.
2. Gets the predicted label for each experiment with `classify_websites.snakefile`.
3. Experiments which are marked invalid by `classify_websites.snakefile` are rerun up to 3 times. If an experiment is still marked invalid after the third run, the predicted label for the experiment is considered unknown.
4. Counts the predicted labels of the final experiments. If a label has a strict majority, the congestion control algorithm of the website is classified as the majority label. Otherwise the algorithm is classified as unknown.
5. The predicted label for the website along with the names of the final experiments used in the prediction are printed and saved to `/tmp/data-processed/[website]-[year][month][day][time].results`, e.g. `cca.org-20190915T103243.results`.

The classification for a website will fail if an error is encountered when running either `ccalg_predict.py` or `classify_websites.snakefile`.

### Logging
`classify_websites.py` logs info to `/tmp/cctestbed-classify-websites.log`.
