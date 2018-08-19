import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from sklearn import preprocessing
from sklearn import neighbors
from sklearn import model_selection

CATEGORIES = ['backoff', 'flatline', 'linear', 'superlinear']
COLORS = plt.rcParams['axes.prop_cycle'].by_key()['color']
FIGSIZE = (8,5)
FONTSIZE = 32

def get_deltas_gradient(flows_resampled):
    # intervals are (a, b] and taking last value
    # this simulates if we had measured the queue size at fixed interval of 1ms
    # can do an "unsampled" gradient but got weird error so did sampling
    deltas = pd.Series(np.gradient(flows_resampled.values), index=flows_resampled.index)
    return deltas

def get_deltas_ratio(flows_resampled):
    samples = flows_resampled
    flow_deltas = samples / samples.shift()
    # fix nans and infinities
    flow_deltas.loc[flow_deltas==np.inf] = samples[flow_deltas==np.inf]
    flow_deltas = flow_deltas.fillna(1)
    # make index start at time 0
    flow_deltas.index = (flow_deltas.index - flow_deltas.index[0]).total_seconds()
    return flow_deltas

def get_labels(flow_deltas):
    flow_labels = []
    for delta in flow_deltas:
        if delta < 1:
            flow_labels.append(CATEGORIES[0]) #backoff
        elif delta == 1:
            flow_labels.append(CATEGORIES[1]) #flatline
        elif delta > 2:
            flow_labels.append(CATEGORIES[3]) #superlinear
        elif delta > 1:
            flow_labels.append(CATEGORIES[2]) #linear
        else:
            raise ValueError('Got deltas with no label: {}'.format(delta))
    # note, index will be the same as deltas
    flow_labels = pd.Series(flow_labels, index=flow_deltas.index)
    return flow_labels

def get_labels_bins(flow_deltas, bins=[0, 1, 1.1, 2, 100]):
    flow_labels =  pd.cut(flow_deltas,
                    bins,
                    labels=CATEGORIES, include_lowest=True)
    # note, index will be the same as deltas
    flow_labels = pd.Series(flow_labels, index=flow_deltas.index)
    return flow_labels

"""
Each flow has it's own flow analyzer.

Lazily populate resample, deltas, and labels properties.
"""
class FlowAnalyzer:
    def __init__(self, experiment_name, experiment, flow_client_port, resample_interval,
                labelsfunc=get_labels, deltasfunc=get_deltas_ratio):
        self.resample_interval = resample_interval
        self.experiment_name = experiment_name
        self.flow = experiment.flows[flow_client_port]
        self.queue_occupancy = self.get_flow_queue_occupancy(experiment)
        self.labelsfunc = labelsfunc
        self.deltasfunc = deltasfunc
        self._resampled = None
        self._deltas = None
        self._labels = None
        self._features = None

    def get_flow_queue_occupancy(self, experiment):
        """Get queue occupancy for flow with matching port number."""
        # flow data will include queue data from enqueue and dequeue
        df_queue = experiment.df_queue
        df_queue = df_queue[df_queue.dropped==0][hex(self.flow.client_port)]
        df_queue = df_queue[df_queue[df_queue!=0].index[0]:df_queue[df_queue!=0].index[-1]]
        df_queue.name = self.flow.ccalg
        # there could be duplicate rows if batch size is every greater than 1
        # want to keep last entry for any duplicated rows
        df_queue = df_queue[~df_queue.index.duplicated(keep='last')]
        return df_queue

    @property
    def resampled(self):
        if self._resampled is None:
            self._resampled =  self.queue_occupancy.resample(
                                '{}ms'.format(self.resample_interval),
                                label='right', closed='right').last().ffill()
        return self._resampled

    @property
    def deltas(self):
        if self._deltas is None:
            self._deltas = self.deltasfunc(self.resampled)
        return self._deltas

    @property
    def labels(self):
        if self._labels is None:
            self._labels = self.labelsfunc(self.deltas)
        return self._labels

    @property
    def features(self):
        if self._features is None:
            flow_features = self.labels.value_counts()
            for cat in CATEGORIES:
                if cat not in flow_features:
                    flow_features[cat] = 0
            #self._features = (flow_features / self.labels.size).sort_index()
            self._features = flow_features.sort_index()
        return self._features

    def scatter_plot(self, figsize=FIGSIZE, fontsize=FONTSIZE):
        df = self.queue_occupancy.to_frame()
        df.index = (df.index - df.index[0]).total_seconds()
        df = df.reset_index()
        ax = df.plot.scatter(x='time', y=self.flow.ccalg,
                                figsize=figsize, fontsize=fontsize)
        ax.set_ylabel('queue size\n (packets)',
                        fontsize=fontsize, fontweight='bold')
        ax.set_xlabel('time (s)',
                        fontsize=fontsize, fontweight='bold')
        return df, ax



############

def plot_flow_with_labels(flow_analyzer, figsize=FIGSIZE, fontsize=FONTSIZE,
                            zoom=None, betterviz=True, legend=True):
    df = flow_analyzer.resampled.to_frame().sort_index()
    df.index = (df.index - df.index[0]).total_seconds()
    df['labels'] = flow_analyzer.labels
    df = df.reset_index()
    # fudging labels
    if betterviz:
        df.loc[df['labels'] == 'backoff', flow_analyzer.flow.ccalg] -= 20
        df.loc[df['labels'] == 'linear', flow_analyzer.flow.ccalg] += 20
        df.loc[df['labels'] == 'superlinear', flow_analyzer.flow.ccalg] += 40
    # assume there will be some backoff labels
    assert((df['labels']==CATEGORIES[0]).sum() > 0)
    pt_color = []
    ax = df[df['labels']==CATEGORIES[0]].plot.scatter(x='time', y=flow_analyzer.flow.ccalg,
                                                        c=COLORS[0], figsize=figsize,
                                                        fontsize=fontsize)
    pt_color.append(mpatches.Patch(color=COLORS[0], label=CATEGORIES[0]))
    for idx, cat in enumerate(CATEGORIES[1:]):
        # must skip over categories for which no point is labeled that way
        if (df['labels']==cat).sum() > 0:
            df[df['labels']==cat].plot.scatter(x='time', y=flow_analyzer.flow.ccalg,
                                                c=COLORS[idx+1], ax=ax)
            pt_color.append(mpatches.Patch(color=COLORS[idx+1], label=cat))
    if legend:
        ax.figure.legend(handles=pt_color, title='label')
    ax.set_ylabel('queue size (packets)', fontsize=fontsize, fontweight='bold')
    ax.set_xlabel('time (s)', fontsize=fontsize, fontweight='bold')
    if zoom:
        ax.set_xlim(zoom[0], zoom[1])
    if betterviz:
        ax.get_yaxis().set_visible(False)
    return df, ax

def plot_flow_features_histogram(labels, noaxis=False,
                                figsize=FIGSIZE, fontsize=FONTSIZE, **kwargs):
    ax = labels.value_counts().sort_index().plot(kind='bar',
                                                figsize=figsize,
                                                fontsize=fontsize, **kwargs)
    if noaxis:
        ax.axes.get_xaxis().set_visible(False)
        ax.axes.get_yaxis().set_visible(False)
    else:
        ax.set_ylabel('count', fontsize=fontsize, fontweight='bold')
        ax.set_xlabel('label', fontsize=fontsize, fontweight='bold')
    return ax

class CCAlgClassifier:
    def __init__(self, training_flow_analyzers):
        self.training_flow_analyzers = training_flow_analyzers
        self._training_samples = {}
        self._true_labels = {}
        self._predicted_labels = {}
        self._classifier = None

    @property
    def true_labels(self):
        if len(self._true_labels) == 0:
            for experiment_name, flow_analyzer in self.training_flow_analyzers.items():
                self._true_labels[experiment_name] = flow_analyzer.flow.ccalg
        return self._true_labels

    @property
    def training_samples(self):
        if len(self._training_samples) == 0:
            for experiment_name, flow_analyzer in self.training_flow_analyzers.items():
                self._training_samples[experiment_name] = flow_analyzer.features
        return self._training_samples

    @property
    def classifier(self):
        if self._classifier is None:
            self._classifier = neighbors.KNeighborsClassifier(n_neighbors=1)
        return self._classifier

    @property
    def predicted_labels(self):
        if len(self._predicted_labels) == 0:
            predicted_labels = model_selection.cross_val_predict(
                    self.classifier,
                    preprocessing.scale(list(self.training_samples.values())),
                    list(self.true_labels.values()))
            for idx, experiment_name in enumerate(self.training_flow_analyzers.keys()):
                self._predicted_labels[experiment_name] = predicted_labels[idx]
        return self._predicted_labels



