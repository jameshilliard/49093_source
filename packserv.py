#!/usr/bin/env python

""" Packet server application.

    This starts a server that serves packet data from a specified serial port
    to TCP sockets.

    Example command line usage:
        python packserv.py /dev/com7 192.168.1.1 55444

    All of the serial port, listeing address, and listening port must be
    provided.
    """


#******************************************************************************
import sys
import os
import datetime
import serial
import threading
import socket
import struct
import tpck
import select
import packet


#******************************************************************************
# Timeout used for serial port and socket reads.
TIMEOUT = 0.1

# Number of bytes from the serial port to process at any given time.
READ_SIZE = 100


#******************************************************************************
def message(msg):
    """ Emit a time-stamped message.
        """
    print '%s: %s' % (str(datetime.datetime.now()), msg)


#******************************************************************************
def shut_down(msg, ser_thrd, connections):
    """ Shut down the server, closing all socket connections and the serial
        port.
        """
    message(msg)
    connections.lock.acquire()
    for c in connections.lst:
        close_socket(c)
    connections.lst = []
    connections.lock.release()
    ser_thrd.stop()


#******************************************************************************
def close_socket(s):
    """ Shut down a connection to a socket.  This accepts a Connection
        instance, not a socket.
        """
    message('Closing connection to %s:%d' % (s.addr[0], s.addr[1]))
    try:
        s.sock.shutdown(2)
    except socket.error:
        pass
    s.sock.close()


#******************************************************************************
class Connection:
    """ Container for a socket and its address.

        We use this to maintain the
        address of a socket even after it has died.
        """

    #--------------------------------------------------------------------------
    def __init__(self, sock, addr):
        """ An connection is created with a socket and an address-tuple.
            """
        self.sock = sock
        self.addr = addr


#******************************************************************************
class ConnectionList:
    """ Thread-safe list of Connection objects.
        """

    #--------------------------------------------------------------------------
    def __init__(self):
        self.lock = threading.RLock()
        self.lst = []


    #--------------------------------------------------------------------------
    def find_socket(self, sock):
        """ Find a socket in the list and return the containing Connection
            object.

            Return None if it isn't found.
            """
        for s in self.lst:
            if s.sock == sock:
                return s
        return None


#******************************************************************************
class RunSerial(threading.Thread):

    #--------------------------------------------------------------------------
    def __init__(self, port, connect_list):
        """ Pass in the serial port and a reference to a list of connections.
            """
        threading.Thread.__init__(self, name = 'Serial Port Listener')
        self.port = port
        self.connections = connect_list
        self.running = False


    #--------------------------------------------------------------------------
    def get_fmt(len_obj):
        """ Return a format string (as required by struct methods) that can
            be used to pack a list of or unpack a string of bytes.

            The length of the returned format string will be the length of the
            len_obj argument.
            """
        return ''.join(['B'] * len(len_obj))

    get_fmt = staticmethod(get_fmt)


    #--------------------------------------------------------------------------
    def run(self):
        """ Watch the serial port.

            Send any received packets to all connected sockets.
            
            If any data is received from any of the connected sockets, convert
            that data to packets and send it to the serial port.

            If any sockets die, remove them from the connection list.
            """
        self.running = True
        tpck_state = None
        try:
            while self.running:
                # Read packets and store them in string form in send_data
                byte_str = self.port.read(READ_SIZE)
                fmt = RunSerial.get_fmt(byte_str)
                bytes = list(struct.unpack(fmt, byte_str))
                pck_list, tpck_state = tpck.parse(bytes, tpck_state)
                send_data = ''.join([str(p) for p in pck_list])

                # Make a list of socket objects from the connection list.
                self.connections.lock.acquire()
                sock_list = [c.sock for c in self.connections.lst]
                self.connections.lock.release()

                # Removals is a list of dead or dying sockets.
                removals = []
                rl, wl, _ = select.select(sock_list, sock_list, [], TIMEOUT)

                for r in rl:
                    try:
                        rx_str = r.recv(1024)

                        # Read data, pack it, then send it.
                        for s in [s for s in rx_str.rsplit('\n') if s]:
                            pck_bytes = tpck.serialize(packet.Packet.from_str(s))
                            fmt = RunSerial.get_fmt(pck_bytes)
                            self.port.write(struct.pack(fmt, *pck_bytes))

                    except socket.error:
                        # rx_str == '' should indicate that a socket closed.  It seems that
                        # this method is required for the cygwin platform as the closed socket
                        # shows up in the readable list, but can't be read from.
                        removals.append(r)

                for w in wl:
                    # Write received data to connected sockets that are still
                    # alive.
                    if w not in removals:
                        try:
                            w.send(send_data)

                        except socket.error:
                            removals.append(w)

                # Remove dead and dying sockets from the connection list.
                self.connections.lock.acquire()
                for r in removals:
                    s = self.connections.find_socket(r)
                    if s is not None:
                        close_socket(s)
                        self.connections.lst.remove(s)
                self.connections.lock.release()

        except:
            # Expected exception handling is buried in the calls within this
            # thread.  Anything else is to major to handle and is most likely
            # caused by the main server thread being killed.
            self.running = False
        
        # Shut down the thread.  Wrap the port-close in a try block in case
        # we are here because the port got closed.
        message('Serial port closing.')
        try:
            self.port.close()
        except (select.error, serial.SerialException):
            pass


    #--------------------------------------------------------------------------
    def stop(self):
        """ Shut down the serial port thread and wait for it to end.
            """
        message('Stopping serial thread.')
        self.running = False
        self.join()


#******************************************************************************
if __name__ == '__main__':
    try:
        ser_name = sys.argv[1]
        host_addr = sys.argv[2]
        port_id = int(sys.argv[3])

    except IndexError:
        print 'Usage:  python packserv.py \'SERIAL_NAME\' \'HOST_ADDR\' \'PORT_ID\''
        print
        print 'Where:   SERIAL_NAME is the name of a serial port, e.g. /dev/ttyACM0'
        print '         HOST_ADDR is the IP address to which connections will be made.'
        print '         PORT_ID is the port number to which connections will be made.'

    else:
        message('Starting server app.  Process ID = %d' % os.getpid())

        message('Opening serial port:  %s' % ser_name)
        try:
            # Get the port up and running.  There's not much point in continuing
            # if we can't get that going.
            serial_port = serial.Serial(ser_name, timeout = TIMEOUT)

        except serial.SerialException:
            message('Could not open serial port.  Exiting.')

        else:
            # Prepare the way for, and start the serial thread.
            connections = ConnectionList()
            serial_thread = RunSerial(serial_port, connections)
            serial_thread.start()
            message('Starting serial thread.')

            try:
                # Get the main server socket up and running.
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind((host_addr, port_id))
                sock.listen(1)
                message('Waiting for incoming connections.')
                message('<CTRL-C> to exit.')

            except socket.error:
                # No server socket.  We still need to kill the serial port, though.
                message('Could not open socket at %s:%d' % (host_addr, port_id))
                serial_thread.stop()

            else:
                try:
                    # Listen for connections, accept them, and add them to the list.
                    # The serial thread will know what to do with them.
                    while True:
                        c, a = sock.accept()
                        connections.lock.acquire()
                        connections.lst.append(Connection(c, a))
                        connections.lock.release()
                        message('Connected to %s:%d' % (a[0], a[1]))

                except KeyboardInterrupt:
                    # Server shutdown is by <CTRL-C>.
                    shut_down('Shutdown by user request.', serial_thread, connections)

                except socket.error:
                    # Shut down if the main server socket dies.
                    shut_down('Socket error.  Forcing shutdown.', serial_thread, connections)

