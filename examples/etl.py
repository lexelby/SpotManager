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

from fabric.api import settings as fabric_settings
from fabric.context_managers import cd, hide
from fabric.contrib import files as fabric_files
from fabric.operations import run, sudo, put
from fabric.state import env

from pyLibrary import aws
from pyLibrary.debugs.logs import Log
from pyLibrary.env.files import File
from pyLibrary.maths import Math
from pyLibrary.meta import use_settings
from pyLibrary.strings import between
from pyLibrary.thread.threads import Lock
from spot.instance_manager import InstanceManager


class ETL(InstanceManager):
    @use_settings
    def __init__(
        self,
        work_queue,  # SETTINGS FOR AWS QUEUE
        connect,  # SETTINGS FOR Fabric `env` TO CONNECT TO INSTANCE
        minimum_utility,
        settings=None
    ):
        InstanceManager.__init__(self, settings)
        self.locker = Lock()
        self.settings = settings

    def required_utility(self):
        queue = aws.Queue(self.settings.work_queue)
        pending = len(queue)
        return max(self.settings.minimum_utility, Math.ceiling(pending / 40))

    def setup(self, instance, utility):
        with self.locker:
            cpu_count = int(round(utility))

            Log.note("setup {{instance}}", instance=instance.id)
            with hide('output'):
                self._config_fabric(instance)
                self._setup_etl_code()
                self._add_private_file()
                self._setup_etl_supervisor(cpu_count)

    def teardown(self, instance):
        with self.locker:
            Log.note("teardown {{instance}}", instance=instance.id)
            self._config_fabric(instance)
            sudo("supervisorctl stop all")

    def _setup_etl_code(self):
        sudo("apt-get update")
        sudo("apt-get clean")

        if not fabric_files.exists("/usr/local/bin/pip"):
            run("mkdir -p /home/ubuntu/temp")

            with cd("/home/ubuntu/temp"):
                # INSTALL FROM CLEAN DIRECTORY
                run("wget https://bootstrap.pypa.io/get-pip.py")
                sudo("python get-pip.py")

        if not fabric_files.exists("/home/ubuntu/TestLog-ETL/README.md"):
            with cd("/home/ubuntu"):
                sudo("apt-get -yf install git-core")
                run('rm -fr /home/ubuntu/TestLog-ETL')
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
        conf_file = File("./examples/config/etl_supervisor.conf")
        content = conf_file.read_bytes()
        find = between(content, "numprocs=", "\n")
        content = content.replace("numprocs=" + find + "\n", "numprocs=" + str(cpu_count) + "\n")
        File("./examples/config/etl_supervisor.conf.alt").write_bytes(content)
        sudo("rm -f /etc/supervisor/conf.d/etl_supervisor.conf")
        put("./examples/config/etl_supervisor.conf.alt", '/etc/supervisor/conf.d/etl_supervisor.conf', use_sudo=True)
        run("mkdir -p /home/ubuntu/TestLog-ETL/results/logs")

        # POKE supervisor TO NOTICE THE CHANGE
        sudo("supervisorctl reread")
        sudo("supervisorctl update")

    def _add_private_file(self):
        run('rm -f /home/ubuntu/private.json')
        put('~/private_active_data_etl.json', '/home/ubuntu/private.json')
        with cd("/home/ubuntu"):
            run("chmod o-r private.json")

    def _config_fabric(self, instance):
        if not instance.ip_address:
            Log.error("Expecting an ip address for {{instance_id}}", instance_id=instance.id)

        for k, v in self.settings.connect.items():
            env[k] = v
        env.host_string = instance.ip_address
        env.abort_exception = Log.error

