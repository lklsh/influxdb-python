# -*- coding: utf-8 -*-

from __future__ import print_function

import datetime
import os
import tempfile
import distutils
import time
import shutil
import subprocess
import unittest
import sys

from influxdb.tests.misc import get_free_port, is_port_open


class InfluxDbInstance(object):
    """ A class to launch of fresh influxdb server instance
    in a temporary place, using a config file template.
    """

    def __init__(self,
                 conf_template,
                 udp_enabled=False):

        if os.environ.get("INFLUXDB_PYTHON_SKIP_SERVER_TESTS", None) == 'True':
            raise unittest.SkipTest(
                "Skipping server test (INFLUXDB_PYTHON_SKIP_SERVER_TESTS)"
            )

        self.influxd_path = self.find_influxd_path()

        # create a temporary dir to store all needed files
        # for the influxdb server instance :
        self.temp_dir_base = tempfile.mkdtemp()

        # "temp_dir_base" will be used for conf file and logs,
        # while "temp_dir_influxdb" is for the databases files/dirs :
        tempdir = self.temp_dir_influxdb = tempfile.mkdtemp(
            dir=self.temp_dir_base)

        # find a couple free ports :
        ports = dict(
            http_port=get_free_port(),
            admin_port=get_free_port(),
            meta_port=get_free_port(),
            udp_port=get_free_port() if udp_enabled else -1,
        )

        conf_data = dict(
            meta_dir=os.path.join(tempdir, 'meta'),
            data_dir=os.path.join(tempdir, 'data'),
            cluster_dir=os.path.join(tempdir, 'state'),
            handoff_dir=os.path.join(tempdir, 'handoff'),
            logs_file=os.path.join(self.temp_dir_base, 'logs.txt'),
            udp_enabled='true' if udp_enabled else 'false',
        )
        conf_data.update(ports)
        self.__dict__.update(conf_data)

        conf_file = os.path.join(self.temp_dir_base, 'influxdb.conf')
        with open(conf_file, "w") as fh:
            with open(conf_template) as fh_template:
                fh.write(fh_template.read().format(**conf_data))

        # now start the server instance:
        self.proc = subprocess.Popen(
            [self.influxd_path, '-config', conf_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        print(
            "%s > Started influxdb bin in %r with ports %s and %s.." % (
                datetime.datetime.now(),
                self.temp_dir_base,
                self.admin_port,
                self.http_port
            )
        )

        # wait for it to listen on the broker and admin ports:
        # usually a fresh instance is ready in less than 1 sec ..
        timeout = time.time() + 10  # so 10 secs should be enough,
        # otherwise either your system load is high,
        # or you run a 286 @ 1Mhz ?
        try:
            while time.time() < timeout:
                if (is_port_open(self.http_port)
                        and is_port_open(self.admin_port)):
                    # it's hard to check if a UDP port is open..
                    if udp_enabled:
                        # so let's just sleep 0.5 sec in this case
                        # to be sure that the server has open the port
                        time.sleep(0.5)
                    break
                time.sleep(0.5)
                if self.proc.poll() is not None:
                    raise RuntimeError('influxdb prematurely exited')
            else:
                self.proc.terminate()
                self.proc.wait()
                raise RuntimeError('Timeout waiting for influxdb to listen'
                                   ' on its ports (%s)' % ports)
        except RuntimeError as err:
            data = self.get_logs_and_output()
            data['reason'] = str(err)
            data['now'] = datetime.datetime.now()
            raise RuntimeError("%(now)s > %(reason)s. RC=%(rc)s\n"
                               "stdout=%(out)s\nstderr=%(err)s\nlogs=%(logs)r"
                               % data)

    def find_influxd_path(self):
        influxdb_bin_path = os.environ.get(
            'INFLUXDB_PYTHON_INFLUXD_PATH',
            None
        )

        if influxdb_bin_path is None:
            influxdb_bin_path = distutils.spawn.find_executable('influxd')
            if not influxdb_bin_path:
                try:
                    influxdb_bin_path = subprocess.check_output(
                        ['which', 'influxdb']
                    ).strip()
                except subprocess.CalledProcessError:
                    # fallback on :
                    influxdb_bin_path = '/opt/influxdb/influxd'

        if not os.path.isfile(influxdb_bin_path):
            raise unittest.SkipTest("Could not find influxd binary")

        version = subprocess.check_output([influxdb_bin_path, 'version'])
        print("InfluxDB version: %s" % version, file=sys.stderr)

        return influxdb_bin_path

    def get_logs_and_output(self):
        proc = self.proc
        try:
            with open(self.logs_file) as fh:
                logs = fh.read()
        except IOError as err:
            logs = "Couldn't read logs: %s" % err
        return {
            'rc': proc.returncode,
            'out': proc.stdout.read(),
            'err': proc.stderr.read(),
            'logs': logs
        }

    def close(self, remove_tree=True):
        self.proc.terminate()
        self.proc.wait()
        if remove_tree:
            shutil.rmtree(self.temp_dir_base)
