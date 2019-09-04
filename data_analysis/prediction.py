import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import matplotlib.patches as mpatches
import itertools as it

from sklearn import preprocessing
from sklearn import neighbors
from sklearn import model_selection

from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import pairwise_distances
from scipy.cluster.hierarchy import dendrogram
import matplotlib.gridspec as gridspec
from sklearn.metrics import adjusted_rand_score
from sklearn.metrics import accuracy_score

from fastdtw import fastdtw
from fastdtw import dtw as dtw_slow
from scipy.spatial.distance import euclidean

from scipy.signal import argrelextrema
import multiprocessing as mp

import matplotlib.style as style
plt.rcParams.update(plt.rcParamsDefault)
style.use(['seaborn-colorblind', 'seaborn-paper', 'seaborn-white'])
plt.rc('font', size=12)
plt.rc('axes', titlesize=12, titleweight='bold', labelsize=12)
plt.rc('xtick', labelsize=12)
plt.rc('ytick', labelsize=12)
plt.rc('legend', fontsize=12)
plt.rc('figure', titlesize=12)
plt.rc('lines', linewidth=3)
plt.rc('axes.spines', right=False, top=False)

#CATEGORIES = ['backoff', 'flatline', 'linear', 'superlinear']
BACKOFF = 'backoff'
FLATLINE = 'flatline'
SUPERLINEAR = 'superlinear'
LINEAR = 'linear'
CATEGORIES = [BACKOFF, FLATLINE, LINEAR, SUPERLINEAR]

COLORS = plt.rcParams['axes.prop_cycle'].by_key()['color']
FIGSIZE = (8,5)
FONTSIZE = 32

ALPHA = 0.002

#TODO:
# data class for feature generation pipeline
class FeatureGenerator:
    def __init__(self, deltasfunc, resamplefunc):
        pass


def get_labels(flow_deltas):
    flow_labels = []
    for delta in flow_deltas:
        if delta < 1:
            flow_labels.append(BACKOFF) #backoff
        elif delta == 1:
            flow_labels.append(FLATLINE) #flatline
        elif delta > 2:
            flow_labels.append(SUPERLINEAR) #superlinear
        elif delta > 1:
            flow_labels.append(LINEAR) #linear
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
    #flow_deltas.index = (flow_deltas.index - flow_deltas.index[0]).total_seconds()
    return flow_deltas

"""
def get_deltas_ewma(flows_resampled):
    assert(not (flows_resampled==0).any())
    deltas = (flows_resampled / flows_resampled.shift()).fillna(1)
    # not sure if i need this additional resampling here
    deltas = deltas.resample('1s').mean().round(4).ffill()
    return deltas
"""

def get_deltas_diff(flows_resampled):
    return flows_resampled.resampled - flows_resampled.resampled.shift()

def resample(queue_occupancy, resample_interval):
    resampled =  queue_occupancy.resample('{}ms'.format(resample_interval),
                                        label='right', closed='right').last().sort_index().ffill()
    # drop zero rows
    resampled = resampled[resampled[resampled!=0].index[0]:resampled[resampled!=0].index[-1]]
    resampled.index = (resampled.index - resampled.index[0]).total_seconds()
    # get just 65 seconds
    resampled = resampled[:65]
    return resampled

def resample_ewma(queue_occupancy, resample_interval, alpha=ALPHA):
    resampled = (queue_occupancy
                    .sort_index()
                    .ewm(alpha=alpha, adjust=False)
                    .mean())
    resampled = resampled.resample('{}ms'.format(resample_interval)).last().ffill()
    resampled.index = (resampled.index - resampled.index[0]).total_seconds()
    return resampled


def get_deltas_ewma(flows_resampled):
    # not implementened
    return flows_resampled

def resample_dtw(queue_occupancy, resample_interval, alpha=ALPHA):
    #return queue_occupancy.reset_index()[queue_occupancy.name] / queue_occupancy.queue_size
    resampled = (queue_occupancy
                    .sort_index()
                    .ewm(alpha=alpha, adjust=False)
                    .mean())
    resampled = resampled.resample('{}ms'.format(resample_interval)).last().ffill()
    resampled.index = (resampled.index - resampled.index[0]).total_seconds()
    #resampled = resampled.ffill()[:65]
    resampled = resampled.ffill()
    return resampled.reset_index()[queue_occupancy.name] #/ queue_occupancy.queue_size

def resample_dtw_znorm(queue_occupancy, resample_interval, alpha=ALPHA):
    #return queue_occupancy.reset_index()[queue_occupancy.name] / queue_occupancy.queue_size
    resampled = (queue_occupancy
                    .sort_index()
                    .ewm(alpha=alpha, adjust=False)
                    .mean())
    resampled = resampled.resample('{}ms'.format(resample_interval)).last().ffill()
    resampled.index = (resampled.index - resampled.index[0]).total_seconds()
    resampled = resampled.ffill()[:65]
    resampled = (resampled - resampled.mean()) / resampled.std()
    return resampled.reset_index()[queue_occupancy.name] #/ queue_occupancy.queue_size

# shorten
def resample_dtw_shorten(queue_occupancy, resample_interval, alpha=ALPHA):
    resampled = (queue_occupancy
                    .sort_index()
                    .ewm(alpha=alpha, adjust=False)
                    .mean())
    resampled = resampled.resample('{}ms'.format(resample_interval)).last().ffill()
    resampled.index = (resampled.index - resampled.index[0]).total_seconds()
    resampled = resampled.ffill()[:30]
    return resampled.reset_index()[queue_occupancy.name]


def get_deltas_dtw(flows_resampled):
    return flows_resampled

def get_labels_dtw(deltas):
    return deltas

def get_features_dtw(labels):
    return labels.round(6)

def get_features_dtw_shorten(labels, num_extrema = 3):
    extrema = argrelextrema(labels.values, np.greater, order=1)[0]
    # if we can get first 2 extrema then do that
    # otherwise just get the whole time series
    if len(extrema) > num_extrema:
        shorten_index = extrema[num_extrema - 1]+1
        if len(labels) > shorten_index:
            return labels.round(6)[:shorten_index]
    return labels.round(6)

def get_labels_histograms(deltas,
                          bins=[0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 50]):
    labels = pd.cut(deltas, bins=bins, include_lowest=True)
    return labels

def get_features_histograms(labels):
    return labels.value_counts().sort_index()

def get_features(labels):
    flow_features = labels.value_counts()
    for cat in CATEGORIES:
        if cat not in flow_features:
            flow_features[cat] = 0
    #self._features = (flow_features / self.labels.size).sort_index()
    return flow_features.sort_index()

def load_flows(experiment_analyzers, queue_sizes, experiment_name_format, flow_where_clause=None,
                deltasfunc=get_deltas_ratio, labelsfunc=get_labels, resamplefunc=resample, featuresfunc=get_features, resample_interval=None):
    # have 64 queue
    #RESAMPLE_INTERVAL = 40
    #LABELSFUNC = lambda x: get_labels_bins(x, bins=[-1000, -1, 0, 1, 1000])
    #DELTASFUNC = get_deltas_gradient
    flow_analyzers = {}
    valid_experiment_names = set([experiment_name_format.format(ccalg, queue_size) for queue_size, ccalg in it.product(queue_sizes, ['reno','cubic','bbr'])])
    for exp_analyzer in experiment_analyzers.values():
        # check if experiment name in queue sizes
        try:
            flow_analyzer = FlowAnalyzer(exp_analyzer, deltasfunc=deltasfunc, labelsfunc=labelsfunc,
                                            resamplefunc=resamplefunc, resample_interval=resample_interval,
                                            featuresfunc=featuresfunc)
            if flow_analyzer.experiment_name in valid_experiment_names:
                flow_analyzers[flow_analyzer.experiment_name] = flow_analyzer
        except KeyError as e:
            pass
            #print('KeyError for experiment_analyzer: {}'.format(exp_analyzer))
    return flow_analyzers

"""
Each flow has it's own flow analyzer.

Lazily populate resample, deltas, and labels properties.
"""
class FlowAnalyzer:
    def __init__(self, experiment_analyzer, flow_client_port=None, resample_interval=None,
                labelsfunc=get_labels_dtw, deltasfunc=get_deltas_dtw, resamplefunc=resample_dtw, featuresfunc=get_features_dtw, flow_where_clause=None):
        self.experiment_name = experiment_analyzer.experiment.name
        self.queue_size = experiment_analyzer.experiment.queue_size
        all_flows = {flow.client_port:flow for flow in experiment_analyzer.experiment.flows}
        if flow_client_port is not None:
            self.flow = all_flows[flow_client_port]
            self.queue_occupancy = self.get_flow_queue_occupancy(experiment_analyzer, flow_where_clause, columns=True)  / self.queue_size
        else:
            self.flow = all_flows[5555]
            self.queue_occupancy = self.get_flow_queue_occupancy(experiment_analyzer, flow_where_clause)  / self.queue_size
            flow_client_port = 5555
        if resample_interval is None:
            resample_interval = self.flow.rtt
        self.resample_interval = resample_interval
        self.labelsfunc = labelsfunc
        self.deltasfunc = deltasfunc
        self.resamplefunc = resamplefunc
        self.featuresfunc = featuresfunc
        self._resampled = None
        self._deltas = None
        self._labels = None
        self._features = None
        self._clusters = None

    def get_flow_queue_occupancy(self, experiment_analyzer, flow_where_clause, columns=False):
        """Get queue occupancy for flow with matching port number."""
        # flow data will include queue data from enqueue and dequeue
        with experiment_analyzer.hdf_queue() as hdf_queue:
            #TODO: this code should work but is broken for now; need to fix bug here
            #df_queue = hdf_queue.select('df_queue',
            #                        where='dropped=0 & src={}'.format(self.flow.client_port),
            #                        columns=[self.flow.client_port])
            if not columns:
                df_queue = hdf_queue.select('df_queue', where=flow_where_clause, columns=['size'])
                df_queue = df_queue['size']
            else:
                df_queue = hdf_queue.select('df_queue', where=flow_where_clause, columns=[self.flow.client_port])
                df_queue = df_queue[self.flow.client_port]

        #df_queue = df_queue[self.flow.client_port]
        #df_queue = df_queue[df_queue[df_queue!=0].index[0]:df_queue[df_queue!=0].index[-1]]
        # df_queue = df_queue['size'] make this is series instead of a dataframe
        #df_queue = df_queue[df_queue[df_queue!=0].index[0]:df_queue[df_queue!=0].index[-1]]
        df_queue.name = self.flow.ccalg
        df_queue = df_queue.sort_index()
        # there could be duplicate rows if batch size is every greater than 1
        # want to keep last entry for any duplicated rows
        df_queue = df_queue[~df_queue.index.duplicated(keep='last')]
        # added for dtw experiments
        df_queue.queue_size = self.queue_size
        return df_queue

    @property
    def resampled(self):
        if self._resampled is None:
            self._resampled = self.resamplefunc(self.queue_occupancy, self.resample_interval)
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
            self._features = self.featuresfunc(self.labels)
        return self._features

    def scatter_plot(self, figsize=FIGSIZE, fontsize=FONTSIZE, **kwargs):
        df = self.queue_occupancy.to_frame()
        df.index = (df.index - df.index[0]).total_seconds()
        df = df.reset_index()
        ax = df.plot.scatter(x='time', y=self.flow.ccalg,
                                figsize=figsize, fontsize=fontsize, **kwargs)
        ax.set_ylabel('queue size\n (packets)',
                        fontsize=fontsize, fontweight='bold')
        ax.set_xlabel('time (s)',
                        fontsize=fontsize, fontweight='bold')
        return df, ax

def plot_flow(flow_analyzer, figsize=FIGSIZE, fontsize=FONTSIZE, **kwargs):
    df = flow_analyzer.resampled.to_frame().reset_index()
    ax = df.plot.scatter(x='time', y=flow_analyzer.flow.ccalg,
                            figsize=figsize, fontsize=fontsize, **kwargs)
    ax.set_ylabel('queue size\n (packets)',
                    fontsize=fontsize, fontweight='bold')
    ax.set_xlabel('time (s)',
                    fontsize=fontsize, fontweight='bold')
    return ax


def plot_flow_with_labels(flow_analyzer, figsize=FIGSIZE, fontsize=FONTSIZE,
                            betterviz=True, legend=True, **kwargs):
    df = flow_analyzer.resampled.to_frame().sort_index()
    #df.index = (df.index - df.index[0]).total_seconds()
    df['labels'] = flow_analyzer.labels
    df = df.reset_index()
    # fudging labels
    if betterviz:
        df.loc[df['labels'] == 'backoff', flow_analyzer.flow.ccalg] -= flow_analyzer.queue_occupancy.max() * 0.02 #5
        df.loc[df['labels'] == 'linear', flow_analyzer.flow.ccalg] += flow_analyzer.queue_occupancy.max() * 0.02
        df.loc[df['labels'] == 'superlinear', flow_analyzer.flow.ccalg] += flow_analyzer.queue_occupancy.max() * 0.04 # 10
    # assume there will be some backoff labels
    assert((df['labels']==BACKOFF).sum() > 0)
    pt_color = []
    ax = df[df['labels']==BACKOFF].plot.scatter(x='time', y=flow_analyzer.flow.ccalg,
                                                        c=COLORS[0], figsize=figsize,
                                                        fontsize=fontsize, **kwargs)
    pt_color.append(mpatches.Patch(color=COLORS[0], label=BACKOFF))
    for idx, cat in enumerate(CATEGORIES[1:]):
        # must skip over categories for which no point is labeled that way
        if (df['labels']==cat).sum() > 0:
            df[df['labels']==cat].plot.scatter(x='time', y=flow_analyzer.flow.ccalg,
                                                c=COLORS[idx+1], ax=ax, **kwargs)
            pt_color.append(mpatches.Patch(color=COLORS[idx+1], label=cat))
    if legend:
        ax.figure.legend(handles=pt_color, title='label', fontsize=fontsize, loc=7, bbox_to_anchor=(0.5, 0.5))
    ax.set_ylabel('queue size (packets)', fontsize=fontsize, fontweight='bold')
    ax.set_xlabel('time (s)', fontsize=fontsize, fontweight='bold')
    if betterviz:
        ax.get_yaxis().set_visible(False)
    return df, ax

def plot_flow_features_histogram(labels, noaxis=False,
                                figsize=FIGSIZE, fontsize=FONTSIZE, **kwargs):

    #ax = labels.value_counts().sort_index().plot(kind='bar',
    #                                            figsize=figsize,
    #                                            fontsize=fontsize, **kwargs)
    ax = labels.plot(kind='bar',figsize=figsize, fontsize=fontsize,**kwargs)
    if noaxis:
        ax.axes.get_xaxis().set_visible(False)
        ax.axes.get_yaxis().set_visible(False)
    else:
        ax.set_ylabel('count', fontsize=fontsize, fontweight='bold')
        ax.set_xlabel('label', fontsize=fontsize, fontweight='bold')
    return ax

class CCAlgClassifier:
    def __init__(self, training_flow_analyzers, testing_flow_analyzers=None, distance_metric=None, normalize=True):
        self.training_flow_analyzers = training_flow_analyzers
        self._training_equals_test = False
        self.testing_flow_analyzers = testing_flow_analyzers
        if self.testing_flow_analyzers is None:
            self._training_equals_test = True
            self.testing_flow_analyzers = training_flow_analyzers
        self._training_samples = None # will be a dataframe
        self._testing_samples = None  # will be a dataframe
        self._true_labels = None      # will be a dataframe
        self._true_labels_training = None
        self._predicted_labels = None # will be a dataframe
        self._classifier = None
        self._distance_metric = distance_metric
        self._results = None
        self._clustering = None
        self._distances = None
        self._avg_label_distances = None
        self._cluster_accuracy = None
        self._avg_distances = None
        self._classifier_accuracy = None
        self.normalize = normalize
        self._clusters = None

    @property
    def true_labels(self):
        if self._true_labels is None:
            true_labels = {}
            for experiment_name, flow_analyzer in self.testing_flow_analyzers.items():
                true_labels[experiment_name] = flow_analyzer.flow.ccalg
            self._true_labels = pd.DataFrame.from_dict(true_labels, orient='index', columns=['true_label']).sort_index()
        return self._true_labels

    @property
    def true_labels_training(self):
        if self._true_labels_training is None:
            true_labels = {}
            for experiment_name, flow_analyzer in self.training_flow_analyzers.items():
                true_labels[experiment_name] = flow_analyzer.flow.ccalg
            self._true_labels_training = pd.DataFrame.from_dict(true_labels, orient='index', columns=['true_label']).sort_index()
        return self._true_labels_training

    @property
    def training_samples(self):
        if self._training_samples is None:
            training_samples = {}
            for experiment_name, flow_analyzer in self.training_flow_analyzers.items():
                # normalized counts
                if self.normalize:
                    training_samples[experiment_name] = flow_analyzer.features / flow_analyzer.features.sum()
                else:
                    training_samples[experiment_name] = flow_analyzer.features
            self._training_samples = pd.DataFrame.from_dict(training_samples, orient='index').sort_index()
            # added for dynamic time warping
            if self._distance_metric == dtw or self._distance_metric == slowdtw or self._distance_metric == euclidean:
                self._training_samples = self._training_samples.fillna(0)
                if self._training_samples.shape[1] < self.testing_samples.shape[1]:
                    # get padding column names from testing samples
                    padding_col_names = self.testing_samples.columns[self._training_samples.shape[1]:]
                    padding = pd.DataFrame(np.zeros((self._training_samples.shape[0],
                      padding_col_names.shape[0])), columns=padding_col_names,
                      index = self._training_samples.index)
                    self._training_samples = pd.concat([self._training_samples, padding], axis=1)
        return self._training_samples

    @property
    def testing_samples(self):
        if self._testing_samples is None:
            testing_samples = {}
            for experiment_name, flow_analyzer in self.testing_flow_analyzers.items():
                # normalized counts
                if self.normalize:
                    testing_samples[experiment_name] = flow_analyzer.features / flow_analyzer.features.sum()
                else:
                    testing_samples[experiment_name] = flow_analyzer.features
            self._testing_samples = pd.DataFrame.from_dict(testing_samples, orient='index').sort_index()
            # added for dynamic time warping -- need to pad with zeros
            if self._distance_metric == dtw or self._distance_metric == slowdtw or self._distance_metric == euclidean:
                self._testing_samples = self._testing_samples.fillna(0)
                if self._testing_samples.shape[1] < self.training_samples.shape[1]:
                    padding_col_names = self.training_samples.columns[self._testing_samples.shape[1]:]
                    padding = pd.DataFrame(np.zeros((self._testing_samples.shape[0],
                      padding_col_names.shape[0])), columns=padding_col_names,
                      index = self._testing_samples.index)
                    self._testing_samples = pd.concat([self._testing_samples, padding], axis=1)
        return self._testing_samples

    @property
    def classifier(self):
        if self._classifier is None:
            if self._distance_metric is None:
                self._classifier = neighbors.KNeighborsClassifier(n_neighbors=1)
            else:
                self._classifier = neighbors.KNeighborsClassifier(n_neighbors=1,  metric=self._distance_metric, n_jobs=min(len(self.testing_samples), mp.cpu_count()))
            self._classifier.fit(self.training_samples.values, self.true_labels_training.values.flatten())
        return self._classifier

    @property
    def distances(self):
        if self._distances is None:
            if self._distance_metric is None:
                distances = pairwise_distances(X=self.training_samples.values,
                                                Y=self.training_samples.values)
            else:
                distances = pairwise_distances(X=self.training_samples.values,
                                                Y=self.training_samples.values,
                                                metric=self._distance_metric, n_jobs=min(len(self.training_samples_samples), mp.cpu_count()))
            self._distances = (pd
                                .DataFrame(distances, columns=self.training_samples.index)
                                .set_index(self.training_samples.index))
        return self._distances

    @property
    def clustering(self):
        if self._clustering is None:
            model = AgglomerativeClustering(n_clusters=self.true_labels_training.nunique()[0],
                                                affinity='precomputed',
                                                linkage='average')
            #model = model.fit(self.distances)
            clusters = model.fit_predict(self.distances)
            self._clustering = model
            self._clusters = clusters
        return self._clustering

    @property
    def cluster_accuracy(self):
        if self._cluster_accuracy is None:
            if self._clusters == None:
                self.clustering #.fit_predict(self.distances)
            self._cluster_accuracy = adjusted_rand_score(self.true_labels_training.values.T[0], self._clusters)
        return self._cluster_accuracy

    @property
    def avg_label_distances(self):
        if self._avg_label_distances is None:
            avg_distances = []
            label_groups = self.true_labels_training.groupby('true_label').groups
            for index, exp_names in label_groups.items():
                for ccalg in label_groups.keys():
                    row = {'index': index, 'ccalg': ccalg}
                    distances = self.distances[exp_names].loc[label_groups[ccalg]]
                    row['distance_avg'] = distances.stack().mean()
                    row['distance_std'] = distances.stack().std()
                    # avg distance per label
                    avg_distances.append(row)
            self._avg_label_distances = pd.DataFrame(avg_distances).set_index(['index', 'ccalg'])
        return self._avg_label_distances

    @property
    def avg_distances(self):
        #TODO: remove hardcoding here
        if self._avg_distances is None:
            label_groups = self.true_labels_training.groupby('true_label').groups
            ccalg = label_groups['bbr']
            not_ccalg = label_groups['reno'].append(label_groups['cubic'])
            diff_labels_distances = self.distances[ccalg].loc[not_ccalg]
            diff_labels_distances_avg = diff_labels_distances.stack().mean()
            diff_labels_distances_std = diff_labels_distances.stack().std()
            same_labels_distances = pd.Series([])
            for ccalg, exp_name in label_groups.items():
                same_labels_distances = same_labels_distances.append(self.distances[exp_name].loc[exp_name].unstack())
            same_labels_distances_avg = same_labels_distances.mean()
            same_labels_distances_std = same_labels_distances.std()
            self._avg_distances = pd.DataFrame.from_dict([{'label_kind':'same',
                                                            'avg': same_labels_distances_avg,
                                                            'std': same_labels_distances_std},
                                                            {'label_kind':'different',
                                                            'avg': diff_labels_distances_avg,
                                                            'std': diff_labels_distances_std}]).set_index('label_kind')
        return self._avg_distances

    @property
    def classifier_accuracy(self):
        if self._classifier_accuracy is None:
            self._classifier_accuracy = accuracy_score(self.true_labels,
                                                        self.predicted_labels, normalize=True)
        return self._classifier_accuracy


    @property
    def predicted_labels(self):
        if self._predicted_labels is None:
            if self._training_equals_test is True:
                # use cross validation if training data equals test data
                predicted_labels = model_selection.cross_val_predict(
                    self.classifier,
                    self.testing_samples.values,
                    self.true_labels.values.flatten()
                )
            else:
                predicted_labels = self.classifier.predict(self.testing_samples.values)
            # WRITE IN NOTEBOOK: BUG IN THE WAY I WAS MATCHING PREDICTED LABEL FROM ARRAY TO A PARTICULAR EXPERIMENT
            # self._predicted_labels = {}
            #for idx, experiment_name in enumerate(self.testing_flow_analyzers.keys()):
            #    self._predicted_labels[experiment_name] = predicted_labels[idx]
            # self._predicted_labels = pd.DataFrame.from_dict(self._predicted_labels, orient='index').sort_index()
            self._predicted_labels = pd.DataFrame(predicted_labels, index=self.testing_samples.index)
        return self._predicted_labels

    @property
    def results(self):
        if self._results is None:
            #self._results = self.testing_samples.copy().sort_index()
            # self._results = pd.DataFrame([])
            self._results = self.true_labels.sort_index()
            self._results['predicted_label'] = self.predicted_labels.sort_index()
            # TODO: use StratifiedKFold to do this computation when training equals test
            if not self._training_equals_test:
                dist, index_neighbor = self.classifier.kneighbors(self.testing_samples.values)
                dist = dist.flatten()
                index_neighbor = index_neighbor.flatten()
                self._results['closest_neighbor'] = list(map(lambda x: self.training_samples.iloc[x].name, index_neighbor))
                self._results['closest_distance'] = dist
        return self._results

def histogram_intersection(h1, h2, bins=None):
    #bins = np.diff(bins)
    sm = 0
    assert(len(h1) == len(h2))
    for i in range(len(h1)):
        #sm += min(bins[i]*h1[i], bins[i]*h2[i])
        sm += min(h1[i], h2[i])
    return 1-sm

def dtw(x, y):
    return fastdtw(x, y, dist=euclidean)[0]

def slowdtw(x, y):
    return dtw_slow(x, y, dist=euclidean)[0]

def scale_zero_one(x):
    return (x - x.min()) / (x.max() - x.min())

def get_all_but(name, all_analyzers):
    most_analyzers = {}
    for key,value in all_analyzers.items():
        if key != name:
            for exp_name, flow_analyzer in value.items():
                most_analyzers_key = '{}-{}'.format(key, exp_name)
                most_analyzers[most_analyzers_key] = flow_analyzer
    return most_analyzers

def get_dtw_distances(dtw_path, timeseries_x, timeseries_y):
    all_distances = []
    for map_x, map_y in dtw_path:
        all_distances.append(euclidean(timeseries_x.iloc[map_x],
                                       timeseries_y.iloc[map_y]))
    all_distances = pd.DataFrame(all_distances)
    all_distances.name = 'distance'
    return all_distances

def plot_dtw_distances(dtw_path, timeseries_x, timeseries_y, plot_ax=None, **kwargs):
    xy = pd.concat([timeseries_x, timeseries_y], axis=1)
    if plot_ax is None:
        ax = xy.plot(figsize=FIGSIZE, style='o-', legend=False, **kwargs)
    else:
        ax = xy.plot(figsize=FIGSIZE, style='o-', legend=False, ax=plot_ax, **kwargs)
    for map_x, map_y in dtw_path:
        ax.plot([timeseries_x.index[map_x], timeseries_y.index[map_y]],
                [timeseries_x.iloc[map_x], timeseries_y.iloc[map_y]], linestyle='--', color=COLORS[1])
    return ax

def plot_classifier_results(classifier, queue_sizes, experiment_name_format):
    fig, axs = plt.subplots(3, len(queue_sizes))
    plot_colors_map = {'reno':'blue', 'cubic':'orange', 'bbr':'green'}
    predicted_label_color = classifier.predicted_labels[0].astype('category').cat.rename_categories(plot_colors_map)

    sample_index = 0
    for jdx, ccalg in enumerate(['reno','cubic','bbr']):
        #axs[jdx, 0].text(-4,400, ccalg, fontsize=22)
        axs[jdx, 0].text(-3, 0.45, ccalg, fontsize=22)
        for idx, queue_size in enumerate(queue_sizes):
            experiment_name = experiment_name_format.format(ccalg, queue_size)
            ax = plot_flow_features_histogram(classifier.testing_samples.loc[experiment_name], noaxis=True,
                                                    figsize=(15,5), ylim=(0,1), ax=axs[jdx, idx], width=0.5)
            ax.add_patch(mpatches.Rectangle((-1,0), 5, 1, color=predicted_label_color.loc[experiment_name], alpha=0.5))
            sample_index += 1
            # 100, 4000

    for idx in range(len(queue_sizes)):
            axs[0,idx].set_title(queue_sizes[idx], fontsize=22)

    return fig

def plot_analyzers_resampled(analyzers, queue_sizes, experiment_name_format):
    fig, axs = plt.subplots(len(queue_sizes), 3)

    sample_index = 0
    for jdx, ccalg in enumerate(['reno','cubic','bbr']):
        #axs[jdx, 0].text(-30, 0.45, ccalg, fontsize=22)
        axs[0, jdx].set_title(ccalg, fontsize=22)
        for idx, queue_size in enumerate(queue_sizes):
            experiment_name = experiment_name_format.format(ccalg, queue_size)
            # normalize queue occupancy so from 0 to 1 for uniform plottingß
            #ax = znorm(analyzers[experiment_name].resampled).plot(figsize=(15,15), ylim=(-0.1*queue_size,queue_size*0.1+queue_size), ax=axs[idx, jdx])
            ax = analyzers[experiment_name].resampled.plot(figsize=(15,15), ax=axs[idx, jdx]) # ylim=(-0.1, 1.1)
            ax.set_xlabel('')
            #ax.axes.get_xaxis().set_visible(False)
            #ax.axes.get_yaxis().set_visible(False)
            sample_index += 1

    for idx in range(len(queue_sizes)):
        #axs[idx,0].text(-25, queue_sizes[idx]*0.45, queue_sizes[idx], fontsize=22)
        axs[idx,0].text(-50, 0, queue_sizes[idx], fontsize=22)

    fig.tight_layout()

    return fig

def plot_analyzers_features(analyzers, queue_sizes, experiment_name_format, **kwargs):
    fig, axs = plt.subplots(len(queue_sizes), 3, figsize=(15,15))

    sample_index = 0
    for jdx, ccalg in enumerate(['reno','cubic','bbr']):
        axs[0, jdx].set_title(ccalg, fontsize=FONTSIZE)
        for idx, queue_size in enumerate(queue_sizes):
            experiment_name = experiment_name_format.format(ccalg, queue_size)
            ax = analyzers[experiment_name].features.plot(figsize=(15,15), ax=axs[idx, jdx], **kwargs)
            ax.set_xlabel('')
            if jdx == 0:
                ax.set_ylabel(queue_sizes[idx], fontsize=FONTSIZE)
            sample_index += 1

    fig.tight_layout()

    return fig

def plot_dendrogram(model, **kwargs):
    """Taken from: https://bit.ly/2O8hpUN"""
    # Children of hierarchical clustering
    children = model.children_
    # Distances between each pair of children
    # Since we don't have this information, we can use a uniform one for plotting
    distance = np.arange(children.shape[0])
    # The number of observations contained in each cluster level
    no_of_observations = np.arange(2, children.shape[0]+2)
    # Create linkage matrix and then plot the dendrogram
    linkage_matrix = np.column_stack([children, distance, no_of_observations]).astype(float)
    # Plot the corresponding dendrogram
    return dendrogram(linkage_matrix, **kwargs)

def plot_classifier_clusters(classifier, normalize=True):
    fig = plt.figure(figsize=(15,10))
    plot_num_rows = len(classifier.training_samples)
    grid = gridspec.GridSpec(plot_num_rows, 3, wspace=0.0, hspace=0.0, width_ratios=[0.25,2,2])
    # display dendrogram of clusters
    ax_dendogram = plt.subplot(grid[:, 2])
    ax_dendogram.axis('off')
    clusters = plot_dendrogram(classifier.clustering, orientation='right', ax=ax_dendogram)
    clusters['leaves'].reverse()
    axes = []
    for ax_idx, exp_name_idx in enumerate(clusters['leaves']):
        # display queue occupancy line for this experiment
        ax = plt.subplot(grid[ax_idx, 1])
        ax.axis('off')
        exp_name = classifier.training_samples.index[exp_name_idx]
        """
        if normalize:
            (classifier.training_flow_analyzers[exp_name].resampled / queue_size).plot(ylim=(0,1), ax=ax)
        else:
            classifier.training_flow_analyzers[exp_name].resampled.plot(ylim=(0,1), ax=ax)
        """
        queue_size = int(exp_name.split('-')[-1][:-1])
        flow = classifier.training_flow_analyzers[exp_name].features #/ queue_size)
        flow = (flow - flow.min()) / (flow.max() - flow.min())
        flow.plot(ylim=(0,1), ax=ax)
        axes.append(ax)
        ax = plt.subplot(grid[ax_idx, 0])
        ax.axis('off')
        ax.text(0, 0.5, exp_name.split('-')[0], va='center', ha='left', fontsize=20)
    return fig

# TODO: new function for going from experiment analyzer to plot of experiment competing flows
def plot_competing_flows(experiment_analyzer):
    max_rtt = 0
    flow_queue_occupancy = {}
    for flow in experiment_analyzer.experiment.flows:
        if flow.rtt_measured is not None and flow.rtt_measured > max_rtt:
            max_rtt = flow.rtt_measured
    for flow in experiment_analyzer.experiment.flows:
        flow_analyzer = FlowAnalyzer(experiment_analyzer,
                                    flow_client_port=flow.client_port,
                                    flow_where_clause='src={}'.format(flow.client_port),
                                    labelsfunc=get_labels_dtw,
                                    featuresfunc=get_features_dtw,
                                    deltasfunc=get_deltas_dtw,
                                    resamplefunc=resample_dtw,
                                    resample_interval=max_rtt)
        pass

    return df


