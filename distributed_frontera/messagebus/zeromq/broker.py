# -*- coding: utf-8 -*-

from time import time
from datetime import timedelta
import logging
from argparse import ArgumentParser
from struct import unpack

import zmq
from zmq.eventloop.ioloop import IOLoop
from zmq.eventloop.zmqstream import ZMQStream

from distributed_frontera.settings import Settings
from socket_config import SocketConfig


class Server(object):

    ctx = None
    loop = None
    stats = None
    spiders_in = None
    spiders_out = None
    sw_in = None
    sw_out = None
    db_in = None
    db_out = None

    def __init__(self, hostname, base_port):
        self.ctx = zmq.Context()
        self.loop = IOLoop.instance()
        self.stats = {
            'started': time(),
            'spiders_out_recvd': 0,
            'spiders_in_recvd': 0,
            'db_in_recvd': 0,
            'db_out_recvd': 0,
            'sw_in_recvd': 0,
            'sw_out_recvd': 0
        }

        socket_config = SocketConfig(hostname, base_port)

        spiders_in_s = self.ctx.socket(zmq.XPUB)
        spiders_out_s = self.ctx.socket(zmq.XSUB)
        sw_in_s = self.ctx.socket(zmq.XPUB)
        sw_out_s = self.ctx.socket(zmq.XSUB)
        db_in_s = self.ctx.socket(zmq.XPUB)
        db_out_s = self.ctx.socket(zmq.XSUB)

        spiders_in_s.bind(socket_config.spiders_in())
        spiders_out_s.bind(socket_config.spiders_out())
        sw_in_s.bind(socket_config.sw_in())
        sw_out_s.bind(socket_config.sw_out())
        db_in_s.bind(socket_config.db_in())
        db_out_s.bind(socket_config.db_out())

        self.spiders_in = ZMQStream(spiders_in_s)
        self.spiders_out = ZMQStream(spiders_out_s)
        self.sw_in = ZMQStream(sw_in_s)
        self.sw_out = ZMQStream(sw_out_s)
        self.db_in = ZMQStream(db_in_s)
        self.db_out = ZMQStream(db_out_s)

        self.spiders_out.on_recv(self.handle_spiders_out_recv)
        self.sw_out.on_recv(self.handle_sw_out_recv)
        self.db_out.on_recv(self.handle_db_out_recv)

        self.sw_in.on_recv(self.handle_sw_in_recv)
        self.db_in.on_recv(self.handle_db_in_recv)
        self.spiders_in.on_recv(self.handle_spiders_in_recv)
        logging.basicConfig(format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
            level=logging.INFO)
        self.logger = logging.getLogger("distributed_frontera.messagebus.zeromq.broker.Server")

    def start(self):
        self.logger.info("Started")
        self.log_stats()
        try:
            self.loop.start()
        except KeyboardInterrupt:
            pass

    def log_stats(self):
        self.logger.info(self.stats)
        self.loop.add_timeout(timedelta(seconds=10), self.log_stats)

    def handle_spiders_out_recv(self, msg):
        self.sw_in.send_multipart(msg)
        self.db_in.send_multipart(msg)
        self.stats['spiders_out_recvd'] += 1

    def handle_sw_out_recv(self, msg):
        self.db_in.send_multipart(msg)
        self.stats['sw_out_recvd'] += 1

    def handle_db_out_recv(self, msg):
        self.spiders_in.send_multipart(msg)
        self.stats['db_out_recvd'] += 1

    def handle_db_in_recv(self, msg):
        self.stats['db_in_recvd'] += 1
        if msg[0][0] in ['\x01', '\x00']:
            action, identity, partition_id = self.decode_subscription(msg[0])
            if identity == 'sl':
                self.spiders_out.send_multipart(msg)
                return
            if identity == 'us':
                self.sw_out.send_multipart(msg)
                return
            raise AttributeError('Unknown identity in channel subscription.')

    def handle_sw_in_recv(self, msg):
        if msg[0][0] in ['\x01', '\x00']:
            self.spiders_out.send_multipart(msg)
        self.stats['sw_in_recvd'] += 1

    def handle_spiders_in_recv(self, msg):
        if msg[0][0] in ['\x01', '\x00']:
            self.db_out.send_multipart(msg)
        self.stats['spiders_in_recvd'] += 1

    def decode_subscription(self, msg):
        """

        :param msg:
        :return: tuple of action, identity, partition_id
        where
        action is 1 - subscription, 0 - unsubscription,
        identity - 2 characters,
        partition_id - 8 bit unsigned integer (None if absent)
        """
        if len(msg) == 4:
            return unpack(">B2sB", msg)
        elif len(msg) == 3:
            action, identity = unpack(">B2s", msg)
            return action, identity, None
        raise ValueError("Can't decode subscription correctly.")


def main():
    parser = ArgumentParser(description="Crawl frontier worker.")
    parser.add_argument('--config', type=str,
                        help='Settings module name, should be accessible by import.')
    parser.add_argument('--hostname', type=str,
                        help='Hostname or IP address to bind. Default is 127.0.0.1')
    parser.add_argument('--log-level', '-L', type=str, default='INFO',
                        help='Log level, for ex. DEBUG, INFO, WARN, ERROR, FATAL. Default is INFO.')
    parser.add_argument('--port', type=int,
                        help='Base port number, server will bind to 6 ports starting from base. Default is 5550')
    args = parser.parse_args()

    settings = Settings(module=args.config)
    hostname = args.hostname if args.hostname else settings.get("ZMQ_HOSTNAME")
    port = args.port if args.port else settings.get("ZMQ_BASE_PORT")
    server = Server(hostname, port)
    server.logger.setLevel(args.log_level)
    server.start()

if __name__ == '__main__':
    main()
