import asyncio
import logging
import os
import uvloop
from functools import partial
from inspect import isawaitable
from multiprocessing import Process
from ssl import create_default_context, Purpose
from signal import (
    SIGTERM, SIGINT,
    signal as signal_func,
    Signals
)
from socket import (
    socket,
    SOL_SOCKET,
    SO_REUSEADDR,
)

from mach9.http import HttpProtocol
from mach9.signal import Signal
from mach9.timer import update_current_time


class Server:

    def __init__(self, app):
        self.app = app
        self.request_handler = app
        self.signal = Signal()
        self.log = app.log
        self.log_config = app.log_config
        self.listeners = app.listeners
        self.debug = app.debug
        self.netlog = app.netlog
        self.request_timeout = app.request_timeout
        self.request_max_size = app.request_max_size
        self.keep_alive = app.keep_alive

    def get_server_setting(self, protocol, host='127.0.0.1', port=8000,
                           debug=False, ssl=None, sock=None, workers=1,
                           loop=None, backlog=100, has_log=True):
        '''Helper function used by `run`.'''

        if isinstance(ssl, dict):
            # try common aliaseses
            cert = ssl.get('cert') or ssl.get('certificate')
            key = ssl.get('key') or ssl.get('keyfile')
            if cert is None or key is None:
                raise ValueError('SSLContext or certificate and key required.')
            context = create_default_context(purpose=Purpose.CLIENT_AUTH)
            context.load_cert_chain(cert, keyfile=key)
            ssl = context

        server_settings = {
            'protocol': protocol,
            'request_handler': self.request_handler,
            'log': self.log,
            'netlog': self.netlog,
            'host': host,
            'port': port,
            'sock': sock,
            'ssl': ssl,
            'signal': self.signal,
            'debug': debug,
            'request_timeout': self.request_timeout,
            'request_max_size': self.request_max_size,
            'keep_alive': self.keep_alive,
            'loop': loop,
            'backlog': backlog,
            'has_log': has_log
        }
        for event_name, settings_name, reverse in (
                ('before_server_start', 'before_start', False),
                ('after_server_start', 'after_start', False),
                ('before_server_stop', 'before_stop', True),
                ('after_server_stop', 'after_stop', True),
        ):
            listeners = self.listeners[event_name].copy()
            if reverse:
                listeners.reverse()
            # Prepend mach9 to the arguments when listeners are triggered
            listeners = [partial(listener, self.app) for listener in listeners]
            server_settings[settings_name] = listeners

        if debug:
            self.log.setLevel(logging.DEBUG)

        # Serve
        if host and port:
            proto = 'http'
            if ssl is not None:
                proto = 'https'
            self.log.info('Goin\' Fast @ {}://{}:{}'.format(proto, host, port))
        return server_settings

    def run(self, host='127.0.0.1', port=8000, ssl=None,
            sock=None, workers=1, backlog=100, protocol=None):
        protocol = protocol or HttpProtocol
        server_settings = self.get_server_setting(
            protocol, host=host, port=port, debug=self.debug, ssl=ssl,
            sock=sock, workers=workers, backlog=backlog,
            has_log=self.log_config is not None)

        try:
            if workers == 1:
                self.serve(**server_settings)
            else:
                self.serve_multiple(server_settings, workers)
        except:
            self.log.exception(
                'Experienced exception while trying to serve')
        self.log.info('Server Stopped')

    def trigger_events(self, events, loop):
        """Trigger event callbacks (functions or async)

        :param events: one or more sync or async functions to execute
        :param loop: event loop
        """
        for event in events:
            result = event(loop)
            if isawaitable(result):
                loop.run_until_complete(result)

    def serve(self, host, port, request_handler,
              before_start=None,
              after_start=None, before_stop=None, after_stop=None, debug=False,
              request_timeout=60, ssl=None, sock=None, request_max_size=None,
              reuse_port=False, loop=None, protocol=None, backlog=100,
              connections=None, signal=None, has_log=True, keep_alive=True,
              log=None, netlog=None):
        self.loop = loop = uvloop.new_event_loop()
        asyncio.set_event_loop(loop)

        if debug:
            loop.set_debug(debug)

        self.trigger_events(before_start, loop)

        connections = connections if connections is not None else set()
        server = partial(
            protocol,
            loop=loop,
            connections=connections,
            signal=signal,
            request_handler=request_handler,
            request_timeout=request_timeout,
            request_max_size=request_max_size,
            has_log=has_log,
            keep_alive=keep_alive,
            log=log,
            netlog=netlog
        )

        server_coroutine = loop.create_server(
            server,
            host,
            port,
            ssl=ssl,
            reuse_port=reuse_port,
            sock=sock,
            backlog=backlog
        )
        # Instead of pulling time at the end of every request,
        # pull it once per minute
        loop.call_soon(partial(update_current_time, loop))

        try:
            http_server = loop.run_until_complete(server_coroutine)
        except:
            log.exception("Unable to start server")
            return

        self.trigger_events(after_start, loop)

        # Register signals for graceful termination
        for _signal in (SIGINT, SIGTERM):
            try:
                loop.add_signal_handler(_signal, loop.stop)
            except NotImplementedError:
                log.warn('Mach9 tried to use loop.add_signal_handler but it is'
                         ' not implemented on this platform.')
        pid = os.getpid()
        try:
            log.info('Starting worker [{}]'.format(pid))
            loop.run_forever()
        finally:
            log.info("Stopping worker [{}]".format(pid))

            # Run the on_stop function if provided
            self.trigger_events(before_stop, loop)

            # Wait for event loop to finish and all connections to drain
            http_server.close()
            loop.run_until_complete(http_server.wait_closed())

            # Complete all tasks on the loop
            signal.stopped = True
            for connection in connections:
                connection.close_if_idle()

            while connections:
                loop.run_until_complete(asyncio.sleep(0.1))

            self.trigger_events(after_stop, loop)

            loop.close()

    def serve_multiple(self, server_settings, workers):
        server_settings['reuse_port'] = True

        # Handling when custom socket is not provided.
        if server_settings.get('sock') is None:
            sock = socket()
            sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            sock.bind((server_settings['host'], server_settings['port']))
            sock.set_inheritable(True)
            server_settings['sock'] = sock
            server_settings['host'] = None
            server_settings['port'] = None
        log = server_settings['log']

        def sig_handler(signal, frame):
            log.info("Received signal {}. Shutting down.".format(
                Signals(signal).name))
            for process in processes:
                os.kill(process.pid, SIGINT)

        signal_func(SIGINT, lambda s, f: sig_handler(s, f))
        signal_func(SIGTERM, lambda s, f: sig_handler(s, f))

        processes = []
        for _ in range(workers):
            process = Process(target=self.serve, kwargs=server_settings)
            process.daemon = True
            process.start()
            processes.append(process)

        for process in processes:
            process.join()

        # the above processes will block this until they're stopped
        for process in processes:
            process.terminate()
        server_settings.get('sock').close()

    def stop(self):
        self.loop.stop()
