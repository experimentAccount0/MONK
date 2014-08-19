# -*- coding: utf-8 -*-
#
# MONK automated test framework
#
# Copyright (C) 2013 DResearch Fahrzeugelektronik GmbH
# Written and maintained by MONK Developers <project-monk@dresearch-fe.de>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version
# 3 of the License, or (at your option) any later version.
#

"""
This module implements device handling. Using the classes from this module you
can abstract a complete :term:`target device` in a single object. On
instantiation you give it some connections and then (theoretically) let the
device handle the rest.

Example::

    import monk_tf.dev as md
    import monk_tf.conn as mc
    # create a device with a ssh connection and a serial connection
    d=md.Device(
        mc.SshConn('192.168.2.100', 'tester', 'secret'),
        mc.SerialConn('/dev/ttyUSB2', 'root', 'muchmoresecret'),
    )
    # send a command (the same way as with connections)
    print d.cmd('ls -al')
    [...]
"""

import logging
import time
import json

import requests
import pexpect

import conn

logger = logging.getLogger(__name__)

############
#
# Exceptions
#
############

class DeviceException(Exception):
    """ Base class for exceptions of the device layer.
    """
    pass

class CantHandleException(DeviceException):
    """ is raised when a request cannot be handled by the connections of a
    :py:class:`~monk_tf.dev.Device`.
    """
    pass

class UpdateFailedException(DeviceException):
    """ is raised if an update didn't get finished or was rolled back.
    """
    pass


##############################
#
# Devices - currently just one
#
##############################

class Device(object):
    """ is the API abstraction of a :term:`target device`.
    """

    def __init__(self, *args, **kwargs):
        """
        :param conns: list of connections. The following works as well::

            ``Device(OneConnection(...), AnotherConnection(...),...)``

        :param name: Device name for logging purposes.
        """
        self._logger = logging.getLogger("Device")
        self.conns = kwargs.pop("conns", list(args))
        self.name = kwargs.pop("name", self.__class__.__name__)
        self._logger = logging.getLogger("{}:{}".format(
            __name__,
            self.name
        ))

    def cmd(self, msg, expect=None, timeout=30, login_timeout=None):
        """ Send a :term:`shell command` to the :term:`target device`.

        :param msg: the :term:`shell command`.
        :param expect: if you don't expect a prompt in the end but something
                       else, you can add a regex here.
        :param timeout: when command should return without finding what it's
                        looking for in the output. Will raise a
                        :py:exception:`pexpect.Timeout` Exception.

        :return: the standard output of the :term:`shell command`.
        """
        for connection in self.conns:
            try:
                return connection.cmd(
                        msg=msg,
                        expect=expect,
                        timeout=timeout,
                        login_timeout=login_timeout,
                )
            except Exception as e:
                self._logger.exception(e)
        raise CantHandleException(
                "dev:'{}',conns:'{}':could not send cmd '{}'".format(
                    self.name,
                    map(str, self.conns),
                    msg,
        ))

    def log(self, msg):
        """ sends a debug-level message to the logger

        This method is used so often, that a smaller version of it is quite
        comfortable.
        """
        self._logger.debug(msg)

    def __str__(self):
        return "{}({}):name={}".format(
                self.__class__.__name__,
                [str(c) for c in self.conns],
                self.name,
        )

class Hydra(Device):
    """ is the device type of DResearch Fahrzeugelektronik GmbH.
    """

    def update(self, link=None):
        """ update the device to current build from Jenkins.
        """
        self._logger.info("Attempt update to " + str(link or self._update_link))
        if not self.is_updated:
            out = self.cmd("do-update -c && get-update {} && do-update".format(
                link if link else self._update_link,
                ), expect="([lL]ogin: )|([cC]onnection\sto\s[^\s]*\sclosed\.)", timeout=600)
            if "closed" in self.conns[0].exp.after:
                self._logger.debug("reset connection after reboot")
                del self.conns[0]._exp
            self._logger.debug("wait till device recovered from updating")
            time.sleep(240)
            self._logger.debug("continue")
            if not self.is_updated:
                error= "build:{};fw:{};out:{}".format(
                        self.latest_build,
                        self.current_fw_version,
                        out[:100],
                )
                raise UpdateFailedException(error)
        else:
            self._logger.info("Already updated.")

    def __init__(self, *args, **kwargs):
        self._update_link = "http://hydraip-integration.internal.dresearch-fe.de:8080/view/HIPOS/job/HydraIP_UpdateV3_USB_Stick/lastSuccessfulBuild/artifact/rel-hudson/hyp-updateV3-hikirk.zip"
        self._jenkins_link = "http://hydraip-integration.internal.dresearch-fe.de:8080/view/HIPOS/job/daisy-hipos-dfe-closed-hikirk/api/json"
        super(Hydra, self).__init__(*args, **kwargs)

    @property
    def latest_build(self):
        """ get the latest build ID from jenkins
        """
        out = requests.get(self._jenkins_link).text
        return str(max(build["number"] for build in json.loads(out)["builds"]))

    @property
    def current_fw_version(self):
        """ the current version of the installed firmware
        """
        return self.cmd("do-update --current-update-version | awk '{print $2}'")

    @property
    def has_newest_firmware(self):
        """ check whether the installed firmware is the newest on jenkins
        """
        return self.latest_build in self.current_fw_version

    @property
    def is_updated(self):
        """ check whether the device is already updated.

        Currently it is implementd with
        :py:meth:`dev.Hydra.has_newest_firmware`.
        """
        return self.has_newest_firmware

    def reset_config(self):
        """ reset the HydraIP configuration on the device
        """
        self.cmd(
            msg="rm -rf /var/lib/connman/* && hip-activate-config --reset && sync && halt -p",
            timeout=150,
            expect="([lL]ogin:)|([cC]onnection\sto\s[^\s]*\sclosed\.)|(Timeout.*\.)|(INFO - LAN)",
            login_timeout=20,
        )
        if "login" not in self.conns[0].exp.after.lower():
            self._logger.debug("reset connection after config reset")
            del self.conns[0]._exp
        self._logger.debug("wait till device recovered from config reset")
        time.sleep(120)
        self._logger.debug("continue")

class DevelDevice(Hydra):
    """ Use this class instead of your other classes for development purposes

    It does not reset anything and does not update. Everything else should work
    fine, though.
    """

    def update(self, link=None):
        pass

    def __init__(self, *args, **kwargs):
        super(DevelDevice, self).__init__(*args, **kwargs)

    @property
    def latest_build(self):
        return "not supported"

    @property
    def current_fw_version(self):
        return "not supported"

    @property
    def has_newest_firmware(self):
        return "not supported"

    @property
    def is_updated(self):
        return True

    def reset_config(self):
        pass
