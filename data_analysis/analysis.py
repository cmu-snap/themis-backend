import pandas as pd

BYTES_TO_BITS = 8
BITS_TO_MEGABITS = 1.0 / 1000000.0
MILLISECONDS_TO_SECONDS = 1.0 / 1000.0

def get_goodput_total(experiment_analyzer, interval=None):
    if interval is None:
        df_goodput_name = 'df_goodput_total'
    else:
        df_goodput_name = 'df_goodput_total_{}_{}'.format(interval[0],interval[1])
    with experiment_analyzer.hdf_queue('a') as hdf_queue:
        try:
            goodput = hdf_queue.get(df_goodput_name)
        except KeyError:
            # need to create goodput time series
            src_query = 'src=' + ' | src='.join(map(lambda x: str(5555+x),
                                                    range(len(experiment_analyzer.experiment.flows))))
            dequeued = hdf_queue.select('df_queue',
                                        where='dequeued=1 & ({})'.format(src_query),
                                        columns=['src', 'datalen'])
            # total goodput
            if interval is not None:
                dequeued.index = (dequeued.index - dequeued.index[0]).total_seconds()
                dequeued = dequeued[interval[0]:interval[1]]
                dequeued.index = dequeued.index - dequeued.index[0] # noramlize again
                #goodput = (dequeued.groupby('src')['datalen'].sum() * BYTES_TO_BITS * BITS_TO_MEGABITS) / dequeued.index.max()
            goodput = (dequeued.groupby('src')['datalen'].sum() * BYTES_TO_BITS * BITS_TO_MEGABITS) / (dequeued.index.max() - dequeued.index.min()).total_seconds()
            goodput.index = goodput.index = goodput.index.astype('str')
            goodput = goodput.rename(experiment_analyzer.flow_names)#[list(experiment_analyzer.flow_names.values())]
            hdf_queue.put(key=df_goodput_name, value=goodput, format='fixed')
            # TODO: only get total goodput for a specific ccalg
            #goodput = goodput.rename(flows)[list(flows.values())]
            #goodput_describe = (transfer_size / transfer_time).describe().T
    return goodput

def get_goodput_timeseries(experiment_analyzer, window_size=None):
    # use RTT from first flow if window size is not specified
    if window_size is None:
        window_size = experiment_analyzer.experiment.flows[0].rtt
    transfer_time = window_size * MILLISECONDS_TO_SECONDS
    with experiment_analyzer.hdf_queue() as hdf_queue:
        src_query = 'src=' + ' | src='.join(map(lambda x: str(5555+x),
                                                range(len(experiment_analyzer.experiment.flows))))
        dequeued = hdf_queue.select('df_queue',
                                    where='dequeued=1 & ({})'.format(src_query),
                                    columns=['src', 'datalen'])
    transfer_size = (dequeued
                    .groupby('src')
                    .datalen
                    .resample('{}ms'.format(window_size))
                    .sum()
                    .unstack(level='src')
                    .fillna(0))
    transfer_size = (transfer_size * BYTES_TO_BITS) * BITS_TO_MEGABITS
    goodput = transfer_size / transfer_time
    goodput.index = (goodput.index - goodput.index[0]).total_seconds()
    goodput = goodput.rename(columns=experiment_analyzer.flow_names)
    goodput = goodput[list(experiment_analyzer.flow_names.values())]
    return goodput

def plot_queue(experiment_analyzer, window_size=None, **kwargs):
    # when used to plot queue, plotted mean queue occupancy over window size
    if window_size is None:
        window_size = experiment_analyzer.experiment.flows[0].rtt
    df_queue_name = 'df_queue_mean_{}winsize'.format(window_size)
    try:
        with experiment_analyzer.hdf_queue() as hdf_queue:
            queue = hdf_queue.get(df_queue_name)
    except KeyError:
        with experiment_analyzer.hdf_queue('a') as hdf_queue:
            src_query = 'src=' + ' | src='.join(map(lambda x: str(5555+x),
                                                    range(len(experiment_analyzer.experiment.flows))))
            queue = hdf_queue.select('df_queue',
                                    where='{}'.format(src_query),
                                    columns=experiment_analyzer.flow_names.keys())
            queue = queue.resample('{}ms'.format(window_size)).mean().ffill()
            queue.index = (queue.index - queue.index[0]).total_seconds()
            queue = queue.rename(columns=experiment_analyzer.flow_names)
            #hdf_queue.put(key=df_queue_name, value=queue, format='fixed')
    ax = queue.plot(**kwargs)
    ax.set_xlabel('time (seconds)')
    ax.set_ylabel('num packets in queue')
    return ax

    """
    df_queue = experiment_analyzer.df_queue
    queue = df_queue.rename(columns=experiment_analyzer.flow_names)
    sender_ports = list(experiment_analyzer.flow_names.keys())
    flow_names = list(experiment_analyzer.flow_names.values())
    start_time = df_queue[df_queue.sort_index().src.isin(sender_ports)].index[0]

    if size:
        queue = queue[['size'] + flow_names]
    else:
        queue = queue[flow_names]
    queue = queue.loc[start_time:]
    queue = queue.resample('{}ms'.format(window_size)).mean().ffill()
    queue.index = (queue.index - queue.index[0]).total_seconds()
    if len(flow_names) == 1:
        queue = queue[flow_names]
    if plot:
        if len(flow_names) > 1:
            ax = queue.plot(xlim=zoom, **kwargs)
            ax.set_xlabel('time (seconds)')
            ax.set_ylabel('num packets in queue')
        else:
            if drops:
                _, axes = plt.subplots()
                colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
                tmp = df_queue[df_queue.dropped==1]
                tmp.index = (tmp.index - df_queue.index[0]).total_seconds()
                ((tmp['dropped']+tmp['dropped']+128)
                    .reset_index()
                    .plot
                    .scatter(x='time (s)',
                            y='dropped',
                            marker='x',
                            color=colors[1],
                            ax=axes))
                queue.plot(title='Average Queue Size ({}ms window)'.format(window_size), xlim=zoom, ax=axes, **kwargs)
                axes.set_xlabel('time (seconds)')
                axes.set_ylabel('num packets in queue')
            else:
                queue = queue[flow_names]
                #ax = queue.plot(title='Average Queue Size ({}ms window)'.format(window_size), xlim=zoom)
                ax = queue.plot(title='Average Queue Size ({}ms window)'.format(window_size), xlim=zoom, **kwargs)
                ax.set_xlabel('time (seconds)')
                ax.set_ylabel('num packets in queue')
                if hline:
                    ax.axhline(y=hline, linewidth=4, color='r')
        if save:
            return ax
    return queue
    """