#!/usr/bin/env python

""" Socket abstraction to read and write tRPC Packet objects.
    """

#******************************************************************************
import socket

import packet
import trpc_msg

from get_trpc_host import get_trpc_host


#******************************************************************************
class TrpcSocket:

    #**************************************************************************
    def __init__(self, addr = None, port = None):
        """ Create the socket object with a default host address of 'localhost'
            and a default port ID of 55544.
            """
        if addr is None or port is None:
            a, p = get_trpc_host()
            if addr is None:
                addr = a
            if port is None:
                port = p

        self.sock = None
        self.is_open = False
        self.addr = addr
        self.port = port
        self.rx_queue = []


    #**************************************************************************
    def open(self):
        """ Connect to the socket.

            Return True if successful, False if not.
            """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.addr, self.port))
            self.is_open = True
            return True

        except socket.error:
            self.sock = None
            self.is_open = False
            return False
    
    #**************************************************************************
    def IsOpen(self):
        return self.is_open

    #**************************************************************************
    def close(self):
        """ Close the socket.
            """
        if self.sock is not None:
            try:
                self.sock.shutdown(2)
                self.sock.close()

            except socket.error:
                pass

            self.sock = None

            self.is_open = False


    #**************************************************************************
    def read(self):
        """ Read a packet from the socket.  If no packet is avaialble,
            None is returned.

            Otherwise a tHA object is returned.
            """
        if self.sock is not None:
            if len(self.rx_queue) != 0:
                return self.rx_queue.pop(0)

            else:
                # Receive data from the socket and split it into \n-delimited
                # strings.  Convert each string to a packet, then use that
                # packet's data to build a Tn4Packet object.
                rx_data = self.sock.recv(1024).rsplit('\n')
                for st in [r for r in rx_data if r]:
                    self.rx_queue.append(trpc_msg.TrpcPacket.from_rx_packet(st))
        return None


    #**************************************************************************
    def write(self, trpc_packet):
        """ Write a TrpcPacket object to the socket.
            """
        if self.sock is not None:
            self.sock.send(str(trpc_packet.to_tpck()))

