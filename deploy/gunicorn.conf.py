"""fin-remark Flask 主模块 Gunicorn 配置。

放置路径：/home/fin/gunicorn.conf.py
启动命令见 deploy/supervisor.conf.example
"""

bind = "127.0.0.1:8000"
# SQLite 为整库写锁，worker 过多会放大 database is locked；
# 本系统并发量低，2 个足够。切换 PostgreSQL 后可上调到 4~8。
workers = 2
worker_class = "sync"
timeout = 120
keepalive = 5

errorlog = "/home/fin/logs/gunicorn-error.log"
accesslog = "/home/fin/logs/gunicorn-access.log"
loglevel = "info"
proc_name = "fin-remark"

pidfile = "/home/fin/logs/gunicorn.pid"
daemon = False
