#!/usr/bin/env python

from os import environ

# This is the name of the environment variable that sets the default host IP address.
HOST_VAR_NAME = "TRPC_HOST"

# This is the name of the environment variable that sets the default port number.
HOST_PORT_NAME = "TRPC_PORT"

def get_trpc_host():
    """ Provide the host and port from the current environment.

        If TRPC_HOST is not defined, the host address will be "localhost".

        If TRPC_PORT is not defined, the port number will be 55544.

        The result is returned as a (host, port) tuple.  (string, int).
        """
    return (environ.get(HOST_VAR_NAME, "localhost"),
            int(environ.get(HOST_PORT_NAME, 55444)))

