#!/usr/bin/env python

""" A demo implementation of the tpck/trpc/tha protocols.
    """

#******************************************************************************
import sys
import struct
import serial
import threading

#******************************************************************************
UINT8MAX = (2**8)-1
UINT16MAX = (2**16)-1
UINT32MAX = (2**32)-1

#******************************************************************************
# TPCK Codes
_SOF_CODE = 0xCA        # Start-of-frame
_EOF_CODE = 0x35        # End-of-frame
_ESC_CODE = 0x2F        # Escape (stuffing)

# TPCK Types
_TRPC_TYPE = 6          # tpck type - trpc

# THA Setback States
_THA_WAKE_4  = 0x00
_THA_UNOCC_4 = 0x01
_THA_OCC_4   = 0x02
_THA_SLEEP_4 = 0x03
_THA_OCC_2   = 0x04
_THA_UNOCC_2 = 0x05
_THA_AWAY    = 0x06
_THA_CURRENT = 0x07

# THA N/A Values
THA_NA_8  = 0xFF
THA_NA_16 = 0xFFFF
THA_NA_32 = 0xFFFFFFFF

#******************************************************************************
_stuff_list = (_SOF_CODE, _EOF_CODE, _ESC_CODE)

#******************************************************************************
trpc_services = {   0x00 : 'Update',
                    0x01 : 'Request',
                    0x02 : 'Report',
                    0x03 : 'Response:Update',
                    0x04 : 'Response:Request'
                }

#******************************************************************************
trpc_methods = {    0x000 : 'NullMethod',
                    0x107 : 'NetworkError',
                    0x10F : 'ReportingState',
                    0x117 : 'OutdoorTemp',
                    0x11F : 'DeviceAttributes',
                    0x127 : 'ModeSetting',
                    0x12F : 'ActiveDemand',
                    0x137 : 'CurrentTemp',
                    0x13F : 'HeatSetpoint',
                    0x147 : 'CoolSetpoint',
                    0x14F : 'SlabSetpoint',
                    0x157 : 'FanPercent',
                    0x15F : 'TakingAddress',
                    0x167 : 'DeviceInventory',
                    0x16F : 'SetbackEnable',
                    0x177 : 'SetbackState',
                    0X17F : 'SetbackEvents',
                    0x187 : 'FirmwareRevision',
                    0x18F : 'ProtocolVersion',
                    0x197 : 'DeviceType',
                    0x19F : 'DeviceVersion',
                    0x1A7 : 'DateTime'
                }

#******************************************************************************
# Find a key the has value = val
def find_key(dic, val):
    """return the key of dictionary dic given the value"""
    return [k for k, v in dic.iteritems() if v == val][0]

#******************************************************************************
# List of methods that have the address attribute as the first data parameter
address_support_list = (    find_key(trpc_methods, 'DeviceAttribues'),
                            find_key(trpc_methods, 'ModeSetting'),
                            find_key(trpc_methods, 'ActiveDemand'),
                            find_key(trpc_methods, 'CurrentTemperature'),
                            find_key(trpc_methods, 'HeatSetpoint'),
                            find_key(trpc_methods, 'CoolSetpoint'),
                            find_key(trpc_methods, 'SlabSetpoint'),
                            find_key(trpc_methods, 'FanPercent'),
                            find_key(trpc_methods, 'TakingAddress'),
                            find_key(trpc_methods, 'SetbackState'),
                            find_key(trpc_methods, 'SetbackEvents'),
                            find_key(trpc_methods, 'DeiceType'),
                            find_key(trpc_methods, 'DeviceVersion')
                        )

#******************************************************************************
# List of methods that have the setpoint attribute as data parameter after the
# address
setpoint_support_list = (   find_key(trpc_methods, 'HeatSetpoint'),
                            find_key(trpc_methods, 'CoolSetpoint'),
                            find_key(trpc_methods, 'SlabSetpoint'),
                            find_key(trpc_methods, 'FanPercent')
                        )

#******************************************************************************
def _calc_checksum(type, data):
    return sum(data, type + len(data)) & 0xFF

#******************************************************************************
def _pack_bytes(bytes, value):
    packed_data = []
    if value is not None:
        for i in range(bytes):
            packed_data.append((value >> (i*8)) & 0xFF)            
    return packed_data

#******************************************************************************
def _unpack_bytes(bytes, data):
    if bytes == len(data):
        unpacked_data=0
        for i in range(bytes):
            unpacked_data += (data[i] << (i*8))
        return unpacked_data

#******************************************************************************
class Tpck(object):
    """ A tpck object
        """
    #--------------------------------------------------------------------------
    def __init__(self, type=None, data=[]):
        self.type = type
        self.data = data    

    #--------------------------------------------------------------------------
    def serialize(self):
        """ Take a packet object and convert it to a string of bytes that conform
            to the tpck protocol.

            Return the resulting sequence which will include start and end of
            frame delimiters along with escape characters and a checksum to
            validate the data.
            """
        def stuff_byte(b):
            if b in _stuff_list:
                build.append(_ESC_CODE)
            build.append(b)

        build = [_SOF_CODE]
        stuff_byte(len(self.data))
        stuff_byte(self.type)
        for i in self.data:
            stuff_byte(i)
        stuff_byte(_calc_checksum(self.type, self.data))
        build.append(_EOF_CODE)
        return build

#******************************************************************************
class TpckStreamParser(object):
    """ Takes in a byte stream and returns a 
        list of packets have been received.
        """
    def __init__(self):
        self.reset()
               
    #--------------------------------------------------------------------------
    def reset(self):
        self.idx = 0
        self.length = 0
        self.type = 0
        self.data = []
        self.cs = 0
        self.escaped = False

    #--------------------------------------------------------------------------
    def tpck_from_stream(self, bytes):
        """ create tpcks from a byte stream
            """
        pck_list = []
        for b in bytes:
            complete = False
            use_byte = True

            if not self.escaped:
                if b == _SOF_CODE:
                    # Start of frame:  Reset the receiving state
                    self.reset()
                    use_byte = False
                elif b == _ESC_CODE:
                    # Escape:  Ignore the byte and prepare to accept the next one as data
                    self.escaped = True
                    use_byte = False
                elif b == _EOF_CODE:
                    # End of frame:  Ignore byte and flag completion.
                    complete = True
                    use_byte = False

            if use_byte:
                if self.idx == 0:
                    # The 1st byte is the length
                    self.length = b
                elif self.idx == 1:
                    # The 2nd byte is the type
                    self.type = b
                elif (self.idx > 1) and (self.idx < self.length+2):
                    # The next "length" bytes are the data
                    self.data.append(b)
                elif self.idx == self.length+2:
                    # And finally the checksum
                    self.cs = b

                self.idx += 1
                self.escaped = False

            if complete and (self.cs == _calc_checksum(self.type, self.data)):
                pck_list.append(Tpck(self.type, self.data))
        
        return pck_list

#******************************************************************************
class Trpc(Tpck):
    """ A trpc object
        """
    #--------------------------------------------------------------------------
    def __init__(self, service=0x01, method=0x000, data=[]):
        Tpck.__init__(self)
        self.type = _TRPC_TYPE
        self.service = service
        self.method = method
        self.data[5:] = data

    #--------------------------------------------------------------------------
    def __str__(self):
        """ Create a string represntation of the data
            Service: 0x00 Method: 0x0000 Data: 0x0000...
            """
        # The first byte is the service
        service = trpc_services.get(self.data[0])
        # The next four bytes are the byte packet method
        method = trpc_methods.get(_unpack_bytes(4, self.data[1:5]))
        
        # Output beautification
        service = service.ljust(16)
        method = method.ljust(16)

        sm = '%s %s ' % (service, method)

        return ''.join([sm, '<', ''.join(['%02X' % x for x in self.data[5:]]), '>'])

    #--------------------------------------------------------------------------
    # Service property
    def getService(self):
        return _unpack_bytes(1, self.data[0:1])
    def setService(self, service):
        try:
            if service not in trpc_services:
                raise ValueError, "WARNING: unsupported service"
            # if the service is changing invalidate data
            if service != self.service:
                self.data[5:] = []
            self.data[0:1] = _pack_bytes(1, service)
        except ValueError, e:
            print e
            self.data[0:1] = _pack_bytes(1, 0x01)
    service = property(fget=getService, fset=setService)

    #--------------------------------------------------------------------------
    # Method property
    def getMethod(self):
        return _unpack_bytes(4, self.data[1:5])
    def setMethod(self, method):
        try:
            if method not in trpc_methods:
                raise ValueError, "WARNING: unsupported method"
            # if the method is changing invalidate data
            if method != self.method:
                self.data[5:] = []
            self.data[1:5] = _pack_bytes(4, method)
        except ValueError, e:
            print e
            self.data[1:5] = _pack_bytes(4, 0x000)
    method = property(fget=getMethod, fset=setMethod)

#******************************************************************************
class Tha(Trpc):
    """ A tha object
        """
    #--------------------------------------------------------------------------
    @classmethod
    def from_tpck(cls, p):
        """ Create a tHA object from a tpck
            """
        tha_obj = Tha()
        if p.type == _TRPC_TYPE:
            tha_obj.type = _TRPC_TYPE
            tha_obj.data = p.data
            return tha_obj
        return None
    
    #--------------------------------------------------------------------------
    def __init__(self,  service=find_key(trpc_services, 'Request'),
                        method=find_key(trpc_methods 'NullMethod'),
                        address=None,
                        error=None,
                        reporting_state=None,
                        temperature=None,
                        attributes=None,
                        mode=None,
                        demand=None,
                        setback_state=_THA_CURRENT,
                        setpoint=None,
                        enable=None,
                        date_time=None):
                        
        Trpc.__init__(self, service, method)
        self.reporting_state = reporting_state
        self.address = address
        self.setback_state = setback_state
        self.setpoint = setpoint
    
    #--------------------------------------------------------------------------
    # State property
    def getReportingState(self):
        try:
            if self.method != find_key(trpc_methods, 'ReportingState'):
                raise AttributeError, "WARNING: method does not have \"reporting_state\" field"
            return _unpack_bytes(1, self.data[5:6])
        except AttributeError, e:
            print e
            return None
    def setReportingState(self, state):
        if state is not None:
            try:
                if self.method != 0x101:
                    raise AttributeError, "WARNING: method does not have \"reporting_state\" field"
                if state < 0 or state > UINT8MAX:
                    raise ValueError, "WARNING: state out of range"
                self.data[5:6] = _pack_bytes(1, state)
            except (AttributeError, ValueError), e:
                print e
    reporting_state = property(fget=getReportingState, fset=setReportingState)

    #--------------------------------------------------------------------------
    # Address property
    def getAddress(self):
        try:
            if self.method not in address_support_list:
                raise AttributeError, "WARNING: method does not have \"address\" field"
            return _unpack_bytes(2, self.data[5:7])
        except AttributeError, e:
            print e
            return None
    def setAddress(self, address):
        if address is not None:
            try:
                if self.method not in address_support_list:
                    raise AttributeError, "WARNING: method does not have \"address\" field"
                if address < 0 or address > UINT16MAX:                
                    raise ValueError, "WARNING: address out of range"
                self.data[5:7] = _pack_bytes(2, address)
            except (AttributeError, ValueError), e:
                print e
    address = property(fget=getAddress, fset=setAddress) 

    #--------------------------------------------------------------------------
    # Setback State property
    def getSetbackState(self):
        try:
            if self.method not in setpoint_support_list:
                raise AttributeError, "WARNING: method does not have \"setback state\" field"
            return _unpack_bytes(1, self.data[7:8])
        except AttributeError, e:
            print e
            return None
    def setSetbackState(self, state):
        if state is not None:
            try:
                if self.method != 0x177:
                    raise AttributeError, "WARNING: method does not have \"setback state\" field"
                if state < 0 or state > 0x06:
                    raise ValueError, "WARNING: setback state out of range"
                self.data[7:8] = _pack_bytes(1, setpoint)
            except (AttributeError, ValueError), e:
                print e
    setback_state = property(fget=getSetbackState, fset=setSetbackState)

    #--------------------------------------------------------------------------
    # Setpoint property
    def getSetpoint(self):
        try:
            if self.method not in setpoint_support_list:
                raise AttributeError, "WARNING: method does not have \"setpoint\" field"
            return _unpack_bytes(1, self.data[8:9])
        except AttributeError, e:
            print e
            return None
    def setSetpoint(self, setpoint):
        if setpoint is not None:
            try:
                if self.method not in setpoint_support_list:
                    raise AttributeError, "WARNING: method does not have \"setpoint\" field"
                if setpoint < 0 or setpoint > UINT8MAX:
                    raise ValueError, "WARNING: setpoint out of range"
                self.data[8:9] = _pack_bytes(1, setpoint)
            except (AttributeError, ValueError), e:
                print e
    setpoint = property(fget=getSetpoint, fset=setSetpoint)

#******************************************************************************
# Timeout used for serial port and socket reads.
TIMEOUT = 0.1

# Number of bytes from the serial port to process at any given time.
READ_SIZE = 100

#******************************************************************************
class RunSerial(threading.Thread):

    #--------------------------------------------------------------------------
    def __init__(self, port):
        """ Pass in the serial port and a reference to a list of connections.
            """
        threading.Thread.__init__(self, name = 'Serial Port Listener')
        self.port = port
        self.running = False
        self.rx_packets = []
        self.tx_packets = []

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
    def read(self):
        """ Pops the next rx packet from the queue
            """
        if self.rx_packets != []:
            return self.rx_packets.pop(0)
        else:
            return None

    #--------------------------------------------------------------------------
    def write(self, p):
        """ Puts the packet p in the tx queue
            """
        self.tx_packets.append(p)

    #--------------------------------------------------------------------------
    def run(self):
        """ Watch the serial port.

            Send any data that is in the tx_packets buffer
            Put received packets into the rx_packets buffer
            """
        self.running = True
        tpck_parser = TpckStreamParser()
        try:
            while self.running:
                # Read in next byte
                byte_str = self.port.read(READ_SIZE)
                fmt = RunSerial.get_fmt(byte_str)
                bytes = list(struct.unpack(fmt, byte_str))
                pck_list = tpck_parser.tpck_from_stream(bytes)
                # Put received packets into buffer
                for p in pck_list:
                    tha_pck = Tha.from_tpck(p)
                    if tha_pck is not None:
                        self.rx_packets.append(tha_pck)

                # send the next packet out
                if self.tx_packets != []:
                    tha_tx = self.tx_packets.pop(0)
                    pck_bytes = tha_tx.serialize()
                    fmt = RunSerial.get_fmt(pck_bytes)
                    self.port.write(struct.pack(fmt, *pck_bytes))

        except:
            self.running = False
        
        # Shut down the thread.  Wrap the port-close in a try block in case
        # we are here because the port got closed.
        print 'Serial port closing.'
        try:
            self.port.close()
        except (select.error, serial.SerialException):
            pass

    #--------------------------------------------------------------------------
    def stop(self):
        """ Shut down the serial port thread and wait for it to end.
            """
        print 'Stopping serial thread.'
        self.running = False
        self.join()
    
#******************************************************************************
if __name__ == '__main__':
    try:
        ser_name = sys.argv[1]

    except IndexError:
        print 'Usage:  python tha_demo.py \'SERIAL_NAME\''
        print
        print 'Where:   SERIAL_NAME is the name of a serial port, e.g. /dev/com1'

    else:
        print 'Opening serial port: %s' % ser_name
        try:
            # Get the port up and running.  There's not much point in continuing
            # if we can't get that going.
            serial_port = serial.Serial(ser_name, timeout = TIMEOUT)

        except serial.SerialException:
            print 'Could not open serial port.  Exiting.'

        else:
            serial_thread = RunSerial(serial_port)            
            serial_thread.start()
            print 'Starting serial thread.'

            try:
                print '<CTRL-C> to exit.'
                service_id = find_key(trpc_services, 'Update')
                method_id = find_key(trpc_methods, 'ReportingState')
                p = Tha(service=service_id, method=method_id, reporting_state=1)
                print p, '\n'
                serial_thread.write(p)
                while(True):
                    p = serial_thread.read()
                    if p != None: print p

            except KeyboardInterrupt:
                # Serial port is shutdown by <CTRL-C>.
                print 'Shutdown by user request.'
                serial_thread.stop()
                serial_port.close()                

