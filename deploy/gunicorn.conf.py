"""fin-remark Flask 主模块 Gunicorn 配置。

放置路径：/home/fin/gunicorn.conf.py
启动命令见 deploy/supervisor.conf.example
"""

bind = "127.0.0.1:8000"
workers = 4
worker_class = "sync"
timeout = 120
keepalive = 5

errorlog = "/home/fin/logs/gunicorn-error.log"
accesslog = "/home/fin/logs/gunicorn-access.log"
loglevel = "info"
proc_name = "fin-remark"

pidfile = "/home/fin/logs/gunicorn.pid"
daemon = False
