# The monitor and dashboard share process state. Do not enable preload or scale
# to multiple workers/instances without first introducing a separate collector.
workers = 1
worker_class = "gthread"
threads = 4
preload_app = False


def post_worker_init(worker):
    from monitor import start
    start()


def worker_exit(server, worker):
    from monitor import stop
    stop()
