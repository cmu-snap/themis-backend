import json
import redis

redis_host = 'localhost'
redis_port = 6379
redis_password = ''

def queue_experiment(conn, website, filename, btlbw, rtt):
    inputs = {
        'website': website,
        'file': filename,
        'btlbw': btlbw,
        'rtt': rtt
    }

    conn.rpush('queue:experiment', json.dumps(inputs))
    print('Pushed experiment website={}, file={}, btlbw={}, rtt={}'.format(
        website, filename, btlbw, rtt))

def main():
    r = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password)
    queue_experiment(
        r,
        'python.org',
        'https://www.python.org/ftp/python/3.7.0/python-3.7.0-macosx10.6.pkg',
        15,
        355)

if __name__ == '__main__':
    main()
