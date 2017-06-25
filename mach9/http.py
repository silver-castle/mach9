import asyncio
import traceback
from httptools import HttpRequestParser, parse_url
from httptools.parser.errors import HttpParserError

from mach9.exceptions import (
    RequestTimeout, PayloadTooLarge, InvalidUsage, ServerError)
from mach9.response import ALL_STATUS_CODES


class BodyChannel(asyncio.Queue):

    def __init__(self, transport):
        super().__init__()
        self.transport = transport

    def send(self, body_chunk):
        return self.put(body_chunk)

    def receive(self):
        return self.get()

    def close(self):
        self.transport.close()


class ReplyChannel:

    def __init__(self, protocol):
        super().__init__()
        self._protocol = protocol

    async def send(self, message):
        self._protocol.send(message)


class HttpProtocol(asyncio.Protocol):
    __slots__ = (
        # exceptions
        '_request_timeout', '_payload_too_large', '_invalid_usage',
        '_server_error',
        # event loop, connection
        'loop', 'transport', 'connections', 'signal',
        # request params
        'parser', 'url', 'headers',
        # request config
        'request_handler', 'request_timeout', 'request_max_size',
        'request_class', 'body_channel_class', 'reply_channel_class',
        # enable or disable access log / error log purpose
        'has_log', 'log', 'netlog',
        # connection management
        '_total_request_size', '_timeout_handler', '_last_request_time',
        'get_current_time', 'body_channel', 'message')

    def __init__(self, *, loop, request_handler, error_handler, log=None,
                 signal=None, connections=set(), request_timeout=60,
                 request_max_size=None, has_log=True,
                 keep_alive=True, request_class=None,
                 netlog=None, get_current_time=None, _request_timeout=None,
                 _payload_too_large=None, _invalid_usage=None,
                 _server_error=None, body_channel_class=None,
                 reply_channel_class=None):
        '''signal is shared'''
        self.loop = loop
        self.transport = None
        self.parser = None
        self.url = None
        self.headers = None
        self.body_channel = None
        self.message = None
        self.signal = signal
        self.has_log = has_log
        self.log = log
        self.netlog = netlog
        self.connections = connections
        self.request_handler = request_handler
        self.request_class = request_class
        self.body_channel_class = body_channel_class
        self.reply_channel_class = reply_channel_class
        self.error_handler = error_handler
        self.request_timeout = request_timeout
        self.request_max_size = request_max_size
        self.get_current_time = get_current_time
        self._total_request_size = 0
        self._timeout_handler = None
        self._last_request_time = None
        self._request_handler_task = None
        self._request_stream_task = None
        self._keep_alive = keep_alive
        self._request_timeout = _request_timeout or RequestTimeout
        self._payload_too_large = _payload_too_large or PayloadTooLarge
        self._invalid_usage = _invalid_usage or InvalidUsage
        self._server_error = _server_error or ServerError

    @property
    def keep_alive(self):
        return (self._keep_alive
                and not self.signal.stopped
                and self.parser
                and self.parser.should_keep_alive())

    # -------------------------------------------- #
    # Connection
    # -------------------------------------------- #

    def connection_made(self, transport):
        self.connections.add(self)
        self._timeout_handler = self.loop.call_later(
            self.request_timeout, self.connection_timeout)
        self.transport = transport
        self._last_request_time = self.get_current_time()

    def connection_lost(self, exc):
        self.connections.discard(self)
        self._timeout_handler.cancel()

    def connection_timeout(self):
        # Check if
        time_elapsed = self.get_current_time() - self._last_request_time
        if time_elapsed < self.request_timeout:
            time_left = self.request_timeout - time_elapsed
            self._timeout_handler = (
                self.loop.call_later(time_left, self.connection_timeout))
        else:
            if self._request_stream_task:
                self._request_stream_task.cancel()
            if self._request_handler_task:
                self._request_handler_task.cancel()
            exception = self._request_timeout('Request Timeout')
            self.write_error(exception)

    # -------------------------------------------- #
    # Parsing
    # -------------------------------------------- #

    def data_received(self, data):
        # Check for the request itself getting too large and exceeding
        # memory limits
        self._total_request_size += len(data)
        if self._total_request_size > self.request_max_size:
            exception = self._payload_too_large('Payload Too Large')
            self.write_error(exception)

        # Create parser if this is the first time we're receiving data
        if self.parser is None:
            self.headers = []
            self.parser = HttpRequestParser(self)

        # Parse request chunk or close connection
        try:
            self.parser.feed_data(data)
        except HttpParserError:
            exception = self._invalid_usage('Bad Request')
            self.write_error(exception)

    def on_url(self, url):
        self.url = url

    def on_header(self, name, value):
        if name == b'Content-Length' and int(value) > self.request_max_size:
            exception = self._payload_too_large('Payload Too Large')
            self.write_error(exception)

        self.headers.append([name, value])

    def on_headers_complete(self):
        channels = {}
        self.message = self.get_message(self.url)
        channels['body'] = self.body_channel_class(self.transport)
        channels['reply'] = self.reply_channel_class(self)
        self.body_channel = channels['body']
        self._request_handler_task = self.loop.create_task(
            self.request_handler(self.message, channels))

    def on_body(self, body):
        body_chunk = self.get_request_body_chunk(body, False, True)
        self._request_stream_task = self.loop.create_task(
            self.body_channel.put(body_chunk))

    def on_message_complete(self):
        body_chunk = self.get_request_body_chunk(b'', False, False)
        self._request_stream_task = self.loop.create_task(
            self.body_channel.send(body_chunk))

    def get_request_body_chunk(self, content, closed, more_content):
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#request-body-chunk
        '''
        return {
            'content': content,
            'closed': closed,
            'more_content': more_content
        }

    def get_message(self, url):
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#request
        '''
        url_obj = parse_url(url)
        if url_obj.schema is None:
            if self.transport.get_extra_info('sslcontext'):
                scheme = 'https'
            else:
                scheme = 'http'
        else:
            scheme = url_obj.schema.decode()
        path = '' if url_obj.path is None else url_obj.path.decode('utf-8')
        query = b'' if url_obj.query is None else url_obj.query
        return {
            'reply_channel': None,
            'http_version': self.parser.get_http_version(),
            'method': self.parser.get_method().decode(),
            'scheme': scheme,
            'path': path,
            'query_string': query,
            'root_path': '',
            'headers': self.headers,
            'body': b'',
            'body_channel': None,
            'client': self.transport.get_extra_info('peername'),
            'server': self.transport.get_extra_info('socketname')
        }

    def send(self, message):
        transport = self.transport
        status = message.get('status')
        headers = message.get('headers')
        content = message.get('content')
        more_content = message.get('more_content', False)

        keep_alive_timeout = self.request_timeout
        timeout_header = b''
        keep_alive = self.keep_alive
        if keep_alive and keep_alive_timeout is not None:
            timeout_header = b'Keep-Alive: %d\r\n' % keep_alive_timeout

        header_content = b''
        if headers is not None:
            _header_content = []
            if not any(map(lambda h: h[0] == b'Content-Length', headers)):
                _header_content.extend([
                    b'Content-Length: ', str(len(content)).encode(), b'\r\n'])
            for key, value in headers:
                _header_content.extend([key, b': ', value, b'\r\n'])
            header_content = b''.join(_header_content)

        response = (
            b'HTTP/1.1 %d %b\r\n'
            b'Connection: %b\r\n'
            b'%b'
            b'%b\r\n'
            b'%b') % (
                status,
                ALL_STATUS_CODES[status],
                b'keep-alive' if keep_alive else b'close',
                timeout_header,
                header_content,
                content
            )
        transport.write(response)
        if not more_content and not keep_alive:
            transport.close()

    def write_error(self, exception):
        try:
            request = None
            if self.message:
                request = self.request_class(self.message)
            response = self.error_handler.response(request, exception)
            self.send(response.get_message(True))
            if self.has_log:
                extra = {
                    'status': response.status,
                    'host': '',
                    'request': str(request) + str(self.url)
                }
                if response and hasattr(response, 'body'):
                    extra['byte'] = len(response.body)
                else:
                    extra['byte'] = -1
                if request:
                    extra['host'] = '%s:%d' % request.ip,
                    extra['request'] = '%s %s' % (request.method,
                                                  self.url)
                self.netlog.info('', extra=extra)
        except RuntimeError:
            self.log.error(
                'Connection lost before error written @ {}'.format(
                    request.ip if self.request else 'Unknown'))
        except Exception as e:
            self.bail_out(
                'Writing error failed, connection closed {}'.format(repr(e)),
                from_error=True)
        finally:
            self.transport.close()

    def bail_out(self, message, from_error=False):
        if from_error or self.transport.is_closing():
            self.log.error(
                ('Transport closed @ {} and exception '
                 'experienced during error handling').format(
                    self.transport.get_extra_info('peername')))
            self.log.debug(
                'Exception:\n{}'.format(traceback.format_exc()))
        else:
            exception = self._server_error(message)
            self.write_error(exception)
            self.log.error(message)

    def cleanup(self):
        self.parser = None
        self.url = None
        self.headers = None
        self._request_handler_task = None
        self._request_stream_task = None
        self._total_request_size = 0
        self.body_channel = None
        self.message = None

    def close_if_idle(self):
        '''Close the connection if a request is not being sent or received

        :return: boolean - True if closed, false if staying open
        '''
        if not self.parser:
            self.transport.close()
            return True
        return False
