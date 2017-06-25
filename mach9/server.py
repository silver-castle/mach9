import asyncio
import os
import uvloop
from functools import partial
from inspect import isawaitable
from multiprocessing import Process
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


def trigger_events(events, loop):
    """Trigger event callbacks (functions or async)

    :param events: one or more sync or async functions to execute
    :param loop: event loop
    """
    for event in events:
        result = event(loop)
        if isawaitable(result):
            loop.run_until_complete(result)


def serve(host, port, request_handler, error_handler, before_start=None,
          after_start=None, before_stop=None, after_stop=None, debug=False,
          request_timeout=60, ssl=None, sock=None, request_max_size=None,
          reuse_port=False, loop=None, protocol=None, backlog=100,
          register_sys_signals=True, run_async=False, connections=None,
          signal=None, has_log=True, keep_alive=True,
          log=None, netlog=None, request_class=None,
          update_current_time=None, get_current_time=None,
          body_channel_class=None, reply_channel_class=None):
    """Start asynchronous HTTP Server on an individual process.

    :param host: Address to host on
    :param port: Port to host on
    :param request_handler: Mach9 request handler with middleware
    :param error_handler: Mach9 error handler with middleware
    :param before_start: function to be executed before the server starts
                         listening. Takes arguments `app` instance and `loop`
    :param after_start: function to be executed after the server starts
                        listening. Takes  arguments `app` instance and `loop`
    :param before_stop: function to be executed when a stop signal is
                        received before it is respected. Takes arguments
                        `app` instance and `loop`
    :param after_stop: function to be executed when a stop signal is
                       received after it is respected. Takes arguments
                       `app` instance and `loop`
    :param debug: enables debug output (slows server)
    :param request_timeout: time in seconds
    :param ssl: SSLContext
    :param sock: Socket for the server to accept connections from
    :param request_max_size: size in bytes, `None` for no limit
    :param reuse_port: `True` for multiple workers
    :param loop: asyncio compatible event loop
    :param protocol: subclass of asyncio protocol class
    :param has_log: disable/enable access log and error log
    :param log:
    :param netlog:
    :param update_current_time:
    :param get_current_time:
    :param request_class:
    :param body_channel_class:
    :param reply_channel_class:
    :return: Nothing
    """
    if not run_async:
        loop = uvloop.new_event_loop()
        asyncio.set_event_loop(loop)

    if debug:
        loop.set_debug(debug)

    trigger_events(before_start, loop)

    connections = connections if connections is not None else set()
    server = partial(
        protocol,
        loop=loop,
        connections=connections,
        signal=signal,
        request_handler=request_handler,
        error_handler=error_handler,
        request_timeout=request_timeout,
        request_max_size=request_max_size,
        get_current_time=get_current_time,
        has_log=has_log,
        keep_alive=keep_alive,
        log=log,
        request_class=request_class,
        body_channel_class=body_channel_class,
        reply_channel_class=reply_channel_class,
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

    if run_async:
        return server_coroutine

    try:
        http_server = loop.run_until_complete(server_coroutine)
    except:
        log.exception("Unable to start server")
        return

    trigger_events(after_start, loop)

    # Register signals for graceful termination
    if register_sys_signals:
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
        trigger_events(before_stop, loop)

        # Wait for event loop to finish and all connections to drain
        http_server.close()
        loop.run_until_complete(http_server.wait_closed())

        # Complete all tasks on the loop
        signal.stopped = True
        for connection in connections:
            connection.close_if_idle()

        while connections:
            loop.run_until_complete(asyncio.sleep(0.1))

        trigger_events(after_stop, loop)

        loop.close()


def serve_multiple(server_settings, workers):
    """Start multiple server processes simultaneously.  Stop on interrupt
    and terminate signals, and drain connections when complete.

    :param server_settings: kw arguments to be passed to the serve function
    :param workers: number of workers to launch
    :param stop_event: if provided, is used as a stop signal
    :return:
    """
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
        process = Process(target=serve, kwargs=server_settings)
        process.daemon = True
        process.start()
        processes.append(process)

    for process in processes:
        process.join()

    # the above processes will block this until they're stopped
    for process in processes:
        process.terminate()
    server_settings.get('sock').close()
