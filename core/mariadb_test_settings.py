"""Run the baseline suite against a disposable MariaDB database over the root socket."""
from .test_settings import *

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.mysql',
    'NAME': 'wrs_security_baseline',
    'USER': 'root',
    'PASSWORD': '',
    'HOST': '/run/mysqld/mysqld.sock',
    'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"},
    'TEST': {'NAME': 'wrs_security_baseline'},
}}
