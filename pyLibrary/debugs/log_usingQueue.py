# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#


from __future__ import unicode_literals
from __future__ import division

from pyLibrary.debugs.logs import BaseLog
from pyLibrary.strings import expand_template, between
from pyLibrary.thread.threads import Queue


class Log_usingQueue(BaseLog):

    def __init__(self):
        self.queue = Queue("log messages")

    def write(self, template, params):
        self.queue.add(expand_template(template, params))

    def stop(self):
        self.queue.close()

    def pop(self):
        lines = self.queue.pop()
        output = []
        for l in lines.split("\n"):
            if l[19:22] == " - ":
                l = l[22:]
            if l.strip().startswith("File"):
                continue
            output.append(l)
        return "\n".join(output).strip()
