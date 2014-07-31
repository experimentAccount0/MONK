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

""" Device Layer

This layer abstracts a complete :term:`target device` in a single object, which
can be interacted with without worrying about how the actual communication is
handled.

To use this module create a :py:class:`~monk_tf.dev.Device` class.

The package is separated into module exceptions and the device classes.
"""

import logging
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
    """
    is raised when a request cannot be handled by the connections of a
    :py:class:`~monk_tf.dev.Device`.
    """
    pass

class NoIPException(DeviceException):
    """ if a device doesn't have any IP addresses this exception is raised
    """
    pass

class UpdateFailedException(DeviceException):
    """ if an update didn't get finished or was rolled back
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

    def __str__(self):
        return "{}({}):name={}".format(
                self.__class__.__name__,
                [str(c) for c in self.conns],
                self.name,
        )

class Hydra(Device):

    def update(self, link=None):
        if not self.is_updated:
            out = self.cmd("do-update -c && get-update {} && do-update".format(
                link if link else self._update_link,
            ), timeout=600)
            for conn in self.conns:
                conn.disconnect()
            if self.last_returncode != 0 or not self.is_updated:
                raise UpdateFailedException("rc:{};out:\"{}\"".format(
                    self.last_returncode,
                    out,
                ))

    def __init__(self, *args, **kwargs):
        self._update_link = "http://hydraip-integration.internal.dresearch-fe.de:8080/view/HIPOS/job/HydraIP_UpdateV3_USB_Stick/lastSuccessfulBuild/artifact/rel-hudson/hyp-updateV3-hikirk.zip"
        self._jenkins_link = "http://hydraip-integration.internal.dresearch-fe.de:8080/view/HIPOS/job/daisy-hipos-dfe-closed-hikirk/api/json"
        super(Hydra, self).__init__(*args, **kwargs)

    @property
    def latest_build(self):
        out = requests.get(self._jenkins_link).text
        return str(max(build["number"] for build in json.loads(out)["builds"]))

    @property
    def current_fw_version(self):
        return self.cmd("do-update --current-update-version | awk '{print $2}'")

    @property
    def has_newest_firmware(self):
        return self.latest_build in self.current_fw_version

    @property
    def is_updated(self):
        return self.has_newest_firmware

    def reset_config(self):
        try:
            self.cmd("hip-activate-config --reset && halt -p")
        except CantHandleException as e:
            pass
