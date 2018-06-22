from cctestbed_analyze_data import get_experiment_data
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib
import numpy as np
import math

from sklearn import preprocessing
from sklearn import neighbors
from sklearn import model_selection
from sklearn import metrics

from scipy import stats

#cats=['backoff', 'flatline', 'linear', 'superlinear', 'sublinear']
cats=['backoff', 'flatline', 'linear', 'superlinear']
colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

class Experiments():
    def __init__(self, pattern):
        self.experiments, self.df_queues, self.raw_flows = get_experiment_data(pattern)

class Flow():
    def __init__(self, df_queue, col, ccalg):
        self.ccalg = ccalg
        flow = df_queue[df_queue.dropped==0][col]
        flow = flow[flow[flow!=0].index[0]:flow[flow!=0].index[-1]]
        flow.name = ccalg
        # there could be duplicate rows if batch size is every greater than 1
        # want to keep last entry for any duplicated rows
        flow = flow[~flow.index.duplicated(keep='last')]
        self.raw = flow
        self.normalized = normalize(self)
        
    def normalize(self):
        flow = pd.Series(preprocessing.minmax_scale(self.raw), self.raw.index)
        flow.name = self.ccalg
        return flow


def plot_flow_with_labels_v2(flow, h, labels, ccalg, figsize=None, fontsize=None, zoom=None, betterviz=False, legend=True):
    df = flow.resample('{}ms'.format(h)).last().ffill()
    df.index = (df.index - df.index[0]).total_seconds()
    df = df.to_frame()
    df['labels'] = labels
    # fudging labels
    if betterviz:
        df.loc[df['labels'] == 'backoff', ccalg] -= 20
        df.loc[df['labels'] == 'linear', ccalg] += 20
        df.loc[df['labels'] == 'superlinear', ccalg] += 40
    ax = plot_flow_with_labels(df.reset_index(), ccalg, figsize=figsize, fontsize=fontsize, zoom=zoom, legend=legend)
    if betterviz:
        ax.get_yaxis().set_visible(False)
    return ax

########################################################################################

def get_flow(df_queue, col, ccalg):
    # flow data will include queue data from enqueue and dequeue
    flow = df_queue[df_queue.dropped==0][col]
    flow = flow[flow[flow!=0].index[0]:flow[flow!=0].index[-1]]
    flow.name = ccalg
    # there could be duplicate rows if batch size is every greater than 1
    # want to keep last entry for any duplicated rows
    flow = flow[~flow.index.duplicated(keep='last')]
    return flow

def get_flow_normalized(df_queue, col, ccalg):
    flow = get_flow(df_queue, col, ccalg)
    flow = pd.Series(preprocessing.minmax_scale(flow), flow.index)
    flow.name=ccalg
    return flow
    
def get_deltas(flow, h):
    # intervals are (a, b] and taking last value
    # this simulates if we had measured the queue size at fixed interval of 1ms
    samples = flow.resample('{}ms'.format(h),  label='right', closed='right').last().ffill()
    # can do an "unsampled" gradient but got weird error so did sampling
    deltas = pd.Series(np.gradient(samples.values), index=samples.index)
    return deltas

def get_deltas_mean(flow, h):
    samples = flow.resample('{}ms'.format(h),  label='right', closed='right').mean().ffill()
    # can do an "unsampled" gradient but got weird error so did sampling
    deltas = pd.Series(np.gradient(samples.values), index=samples.index)
    return deltas

def get_deltas_v3(flow, h):
    samples = flow.resample('{}ms'.format(h),  label='right', closed='right').mean().ffill()
    # can do an "unsampled" gradient but got weird error so did sampling
    deltas = pd.Series(np.gradient(samples.values), index=samples.index)
    return deltas.diff().fillna(0)

def get_deltas_v2(flow, h):
    samples = flow.rolling('1s').mean().resample('{}ms'.format(h)).last().ffill()
    deltas = samples.diff()
    return deltas

def get_labels(deltas, categories=cats, bins=None):
    # CUTOFFS DEFINED HERE
    if not bins:
        bins = [min(deltas.min(), -2), -1, 0, 1, max(deltas.max(),2)]
    labels =  pd.cut(deltas, 
                    bins, 
                    labels=categories, include_lowest=True)
    labels.index = (labels.index - labels.index[0]).total_seconds()
    return labels

def get_labels_v2(deltas, bound_flatline=(-0.1 ,0.1)):
    first_deriv = deltas
    second_deriv = first_deriv.abs().diff().fillna(0)
    labels = []
    for idx, deriv in enumerate(first_deriv):
        if (deriv==bound_flatline[0] or deriv==bound_flatline[1]) or (deriv > bound_flatline[0]) and (deriv < bound_flatline[1]): #and second_deriv[idx] == 0:
            labels.append('flatline')
        elif deriv < bound_flatline[0]: #and second_deriv[idx] == 0:
            labels.append('backoff')
        elif deriv > bound_flatline[1] and ((second_deriv[idx]==bound_flatline[0] or second_deriv[idx]==bound_flatline[1]) or (second_deriv[idx] > bound_flatline[0]) and (second_deriv[idx] < bound_flatline[1])):
            labels.append('linear')
        elif deriv > bound_flatline[1] and second_deriv[idx] > bound_flatline[1]:
            labels.append('superlinear')
        elif deriv > bound_flatline[1] and second_deriv[idx] < bound_flatline[0]:
            labels.append('sublinear')
        else:
            raise ValueError('Got values with no labels: first_deriv={}, second_deriv={}'.format(deriv, second_deriv[idx]))
    labels = pd.Series(labels, index=(first_deriv.index - first_deriv.index[0]).total_seconds())
    return labels

def get_flow_with_labels(df_queue, col, ccalg, h, deltasfunc=get_deltas, flowfunc=get_flow, bins=None):
    # get labels
    flow = flowfunc(df_queue, col, ccalg)
    deltas = deltasfunc(flow, h)
    if callable(bins):
        #labels = get_labels(deltas, bins=bins(deltas))
        #labels = get_labels_v2(deltas, bound_flatline=bins)
        #labels = get_labels_v2(deltas, bound_flatline=bins)
        labels = get_labels(deltas, bins=bins(deltas))
    else:
        labels = get_labels(deltas, bins=bins)
        #labels = get_labels_v2(deltas, bound_flatline=bins)
    labels.name = ccalg

    df = flow.reset_index()
    df['time'] = (df['time'] - df['time'][0]).dt.total_seconds()
    # repeating cut twice so I can get labels and the bins it falls between
    # df['labels'] = pd.Series(pd.cut(df.time, 
    #                bins=labels.index.values,
    #                labels=labels.iloc[1:].values,
    #                include_lowest=True))
    # df['bins'] = pd.Series(pd.cut(df.time, 
    #                bins=labels.index.values,
    #                include_lowest=True))
    #return flow
    return flow, deltas, labels, df


def plot_flow_with_labels(df, ccalg, h=None, zoom=None, figsize=None, fontsize=None, legend=True):
    pt_color = []
    ax = df[df['labels']==cats[0]].plot.scatter(x='time', y=ccalg, c=colors[0], figsize=figsize, fontsize=fontsize) 
    pt_color.append(mpatches.Patch(color=colors[0], label=cats[0]))
    for idx, cat in enumerate(cats[1:]):
        df[df['labels']==cat].plot.scatter(x='time', y=ccalg, c=colors[idx+1], ax=ax)
        pt_color.append(mpatches.Patch(color=colors[idx+1], label=cat))
    if legend:
        ax.figure.legend(handles=pt_color, title='label')
    ax.set_ylabel('queue size (packets)', fontsize=fontsize)
    ax.set_xlabel('time (s)', fontsize=fontsize)
    if zoom:
        ax.set_xlim(zoom[0], zoom[1])
    ax.figure
    return ax

def plot_flow_with_deltas(flow, deltas, ccalg, h, queue_size, zoom=None, line=False, vrange=None, figsize=None):
    df = flow.resample('{}ms'.format(h)).last().ffill()
    df.index = (df.index - df.index[0]).total_seconds()
    df.name = ccalg
    df = df.reset_index()
    df['delta'] = deltas.values
    figure, ax = plt.subplots(figsize=figsize)
    if line:
        df.set_index('time')[ccalg].plot(ax=ax)
    if vrange:
        vmin, vmax = vrange
    else:
        vmin, vmax = None, None
    df.plot.scatter(x='time', y=ccalg, 
                        c='delta', #s=100,
                        cmap=plt.cm.get_cmap('coolwarm'), 
                        #title='max queue size = {}'.format(queue_size),
                        ax=ax, vmin=vmin, vmax=vmax)
    
    #ax.set_ylabel('queue occpancy (normalized)')
    ax.set_ylabel('queue size')
    if zoom:
        ax.set_xlim(zoom[0], zoom[1])
    return ax
    
    
def get_flow_features(labels):
    features = labels.value_counts()
    for cat in cats:
        if cat not in features:
            features[cat] = 0
    return (features / labels.size).sort_index() #(labels.value_counts() / labels.size).sort_index()

def get_flow_features_raw(labels):
    return labels.value_counts().sort_index()


def get_all_flows_with_labels(df_queues_reno,
                             flows_reno, 
                             df_queues_cubic,
                             flows_cubic,
                             df_queues_bbr,
                             flows_bbr,
                            h=40, deltasfunc=get_deltas, bins=None, flowfunc=get_flow, smallest_queue_size=8):
    results = {'reno' : {'labels': {}, 'flow':{}, 'deltas':{}, 'df':{}},
            'cubic': {'labels': {}, 'flow':{}, 'deltas':{}, 'df':{}},
            'bbr': {'labels': {}, 'flow':{}, 'deltas':{}, 'df':{}}}
    for df_queues, flows, ccalg in zip([df_queues_reno, df_queues_cubic, df_queues_bbr], 
                                    [flows_reno, flows_cubic, flows_bbr],
                                    ['reno', 'cubic', 'bbr']):
        for queue_size in sorted(df_queues.keys())[int(math.log(smallest_queue_size,2)-2):]:
            (results[ccalg]['flow'][queue_size], 
            results[ccalg]['deltas'][queue_size], 
            results[ccalg]['labels'][queue_size],
            results[ccalg]['df'][queue_size]) = get_flow_with_labels(
                    df_queue=df_queues[queue_size], 
                    col=list(flows[queue_size].keys())[0], 
                    ccalg=ccalg, 
                    h=h, 
                    deltasfunc=deltasfunc, 
                    flowfunc=flowfunc, 
                    bins=bins)

    return results

def get_all_flows_with_labels_v2(*experiments, h=40, deltasfunc=get_deltas, bins=None, flowfunc=get_flow, 
    smallest_queue_size=8):
    results = {}
    template_row = {'labels': {}, 'flow':{}, 'deltas':{}, 'df':{}}
    for exp in experiments: 
        df_queues, flows, ccalg = exp
        results[ccalg] = template_row.copy()
        for queue_size in sorted(df_queues.keys())[int(math.log(smallest_queue_size,2)-2):]:
            (results[ccalg]['flow'][queue_size], 
            results[ccalg]['deltas'][queue_size], 
            results[ccalg]['labels'][queue_size],
            results[ccalg]['df'][queue_size]) = get_flow_with_labels(
                    df_queue=df_queues[queue_size], 
                    col=list(flows[queue_size].keys())[0], 
                    ccalg=ccalg, 
                    h=h, 
                    deltasfunc=deltasfunc, 
                    flowfunc=flowfunc, 
                    bins=bins)
    return results
    

def get_all_flow_features(labels_reno, labels_cubic, labels_bbr, df_queues_reno, df_queues_cubic, df_queues_bbr):
    true_labels = []
    samples = []
    for idx, labels_ccalg, df_queues, ccalg in zip([0,1,2], [labels_reno, labels_cubic, labels_bbr], [df_queues_reno, df_queues_cubic, df_queues_bbr], ['reno','cubic','bbr']):
        for queue_size, labels in labels_ccalg.items():
            true_labels.append(idx)
            p = get_flow_features(labels).values
            #p = get_flow_features_raw(labels).values
            tmp = df_queues[queue_size].resample('400ms').apply(lambda x: abs(x.max() - x.min())/x.max())
            tmp_zscore =  pd.Series(stats.zscore(tmp))
            percent_drop = tmp.reset_index()[tmp_zscore.abs() > 1][ccalg].value_counts().idxmax()
            #p = np.append(p, percent_drop)
            #p = np.append(p, queue_size)
            samples.append(p)

    return samples, true_labels
    
def classify_1nn(labels_reno, labels_cubic, labels_bbr, df_queues_reno, df_queues_cubic, df_queues_bbr):

    samples, true_labels = get_all_flow_features(labels_reno, labels_cubic, labels_bbr, df_queues_reno, df_queues_cubic, df_queues_bbr)
    predicted = model_selection.cross_val_predict(neighbors.KNeighborsClassifier(n_neighbors=1),
                                                 preprocessing.scale(samples),
                                                 true_labels)
    return samples, predicted, true_labels

def classify_1nn_v2(all_flows, ccalgs):
    samples, true_labels = get_all_flow_features(all_flows, ccalgs)
    predicted = model_selection.cross_val_predict(neighbors.KNeighborsClassifier(n_neighbors=1),
                                                 preprocessing.scale(samples),
                                                 true_labels)
    return samples, predicted, true_labels

def get_all_flow_features_v2(all_flows, ccalgs):
    true_labels = []
    samples = []
    for idx, arg in enumeate(args):
        labels_ccalg, df_queues, ccalg = arg
        for queue_size, labels in labels_ccalg.items():
            true_labels.append(idx)
            p = get_flow_features(labels).values
            #p = get_flow_features_raw(labels).values
            tmp = df_queues[queue_size].resample('400ms').apply(lambda x: abs(x.max() - x.min())/x.max())
            tmp_zscore =  pd.Series(stats.zscore(tmp))
            percent_drop = tmp.reset_index()[tmp_zscore.abs() > 1][ccalg].value_counts().idxmax()
            #p = np.append(p, percent_drop)
            #p = np.append(p, queue_size)
            samples.append(p)

    return samples, true_labels

def classify_kmeans(labels_reno, labels_cubic, labels_bbr):
    pass
    
    
