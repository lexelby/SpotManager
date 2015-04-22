# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import unicode_literals
from __future__ import division
from math import log10

from fabric.api import settings as fabric_settings
from fabric.context_managers import cd
from fabric.contrib import files as fabric_files
from fabric.operations import run, sudo, put
from fabric.state import env

from pyLibrary import aws

from pyLibrary.debugs.logs import Log
from pyLibrary.env.files import File
from pyLibrary.meta import use_settings
from pyLibrary.strings import between

from spot.instance_manager import InstanceManager


class ETL(InstanceManager):
    @use_settings
    def __init__(
        self,
        work_queue,  # SETTINGS FOR AWS QUEUE
        connect,     # SETTINGS FOR Fabric `env` TO CONNECT TO INSTANCE
        settings=None
    ):
        InstanceManager.__init__(self, settings)
        self.settings = settings

    def required_utility(self):
        queue = aws.Queue(self.settings.work_queue)
        pending = len(queue)
        # SINCE EACH ITEM IN QUEUE REPRESENTS SMALL, OR GIGANTIC, AMOUNT
        # OF TOTAL WORK THE QUEUE SIZE IS TERRIBLE PREDICTOR OF HOW MUCH
        # UTILITY WE REALLY NEED.  WE USE log10() TO SUPPRESS THE
        # VARIABILITY, AND HOPE FOR THE BEST
        return max(2, log10(max(pending, 1)) * 10)

    def setup_instance(self, instance, utility):
        cpu_count = int(round(utility))

        self._config_fabric(instance)
        self._setup_etl_code()
        self._add_private_file()
        self._setup_etl_supervisor(cpu_count)

    def teardown_instance(self, instance):
        self._config_fabric(instance)
        sudo("supervisorctl stop all")

    def _setup_etl_code(self):
        sudo("sudo apt-get update")

        if not fabric_files.exists("/home/ubuntu/temp"):
            run("mkdir -p /home/ubuntu/temp")

            with cd("/home/ubuntu/temp"):
                # INSTALL FROM CLEAN DIRECTORY
                run("wget https://bootstrap.pypa.io/get-pip.py")
                sudo("python get-pip.py")

        if not fabric_files.exists("/home/ubuntu/TestLog-ETL"):
            with cd("/home/ubuntu"):
                sudo("apt-get -y install git-core")
                run("git clone https://github.com/klahnakoski/TestLog-ETL.git")

        with cd("/home/ubuntu/TestLog-ETL"):
            run("git checkout etl")
            # pip install -r requirements.txt HAS TROUBLE IMPORTING SOME LIBS
            sudo("pip install MozillaPulse")
            sudo("pip install boto")
            sudo("pip install requests")
            sudo("apt-get -y install python-psycopg2")

    def _setup_etl_supervisor(self, cpu_count):
        # INSTALL supervsor
        sudo("apt-get install -y supervisor")
        with fabric_settings(warn_only=True):
            run("service supervisor start")

        # READ LOCAL CONFIG FILE, ALTER IT FOR THIS MACHINE RESOURCES, AND PUSH TO REMOTE
        conf_file = File("./resources/supervisor/etl.conf")
        content = conf_file.read_bytes()
        find = between(content, "numprocs=", "\n")
        content = content.replace("numprocs=" + find + "\n", "numprocs=" + str(cpu_count * 2) + "\n")
        File("./resources/supervisor/etl.conf.alt").write_bytes(content)
        sudo("rm -f /etc/supervisor/conf.d/etl.conf")
        put("./resources/supervisor/etl.conf.alt", '/etc/supervisor/conf.d/etl.conf', use_sudo=True)
        run("mkdir -p /home/ubuntu/TestLog-ETL/results/logs")

        # POKE supervisor TO NOTICE THE CHANGE
        sudo("supervisorctl reread")
        sudo("supervisorctl update")

    def _add_private_file(self):
        put('~/private.json', '/home/ubuntu')
        with cd("/home/ubuntu"):
            run("chmod o-r private.json")

    def _config_fabric(self, instance):
        for k, v in self.settings.connect.items():
            env[k] = v
        env.host_string = instance.ip_address
        env.abort_exception = Log.error
