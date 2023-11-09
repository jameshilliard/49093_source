#!/usr/bin/env python

""" tRPC terminal

    Listen for tRPC packets and print them to stdout.
    """

import trpc_sock

def main():
    sock = trpc_sock.TrpcSocket()
    if not sock.open():
        print "Could not connect to socket."
    else:
        try:
            while True:
                p = sock.read()
                if p is not None:
                    print p
        except KeyboardInterrupt:
            pass
        sock.close()


if __name__ == "__main__":
    main()
