import asyncio
import traceback
from httptools import HttpParserUpgrade
from httptools import HttpRequestParser, parse_url
from httptools.parser.errors import HttpParserError
from typing import Dict, List, Any, Awaitable

from mach9.exceptions import (
    RequestTimeout, PayloadTooLarge, InvalidUsage, ServerError)
from mach9.response import ALL_STATUS_CODES
from mach9.websocket import upgrade_to_websocket


class BodyChannel(asyncio.Queue):

    def __init__(self, transport):
        super().__init__()
        self.transport = transport

    def send(self, body_chunk):
        return self.put(body_chunk)

    def receive(self):
        return self.get()


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
        'request_class',
        # enable or disable access log / error log purpose
        'has_log', 'log', 'netlog',
        # connection management
        '_is_upgrade',
        '_total_request_size', '_timeout_handler', '_last_request_time',
        'get_current_time', 'body_channel', 'message')

    def __init__(self, *, loop, request_handler: Awaitable, error_handler,
                 log=None, signal=None, connections=set(), request_timeout=60,
                 request_max_size=None, has_log=True,
                 keep_alive=True, request_class=None,
                 netlog=None, get_current_time=None, _request_timeout=None,
                 _payload_too_large=None, _invalid_usage=None,
                 _server_error=None):
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
        self.error_handler = error_handler
        self.request_timeout = request_timeout
        self.request_max_size = request_max_size
        self.get_current_time = get_current_time
        self._total_request_size = 0
        self._timeout_handler = None
        self._last_request_time = None
        self._request_handler_task = None
        self._request_stream_task = None
        self._is_upgrade = False
        # config.KEEP_ALIVE or not check_headers()['connection_close']
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

    def data_received(self, data: bytes):
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
        except HttpParserUpgrade:
            upgrade_to_websocket(self)
        except HttpParserError:
            exception = self._invalid_usage('Bad Request')
            self.write_error(exception)

    def on_url(self, url: bytes):
        self.url = url

    def on_header(self, name: bytes, value: bytes):
        # for websocket
        name = name.lower()
        if name == b'content-length' and int(value) > self.request_max_size:
            exception = self._payload_too_large('Payload Too Large')
            self.write_error(exception)
        if name == b'upgrade':
            self._is_upgrade = True
        self.headers.append([name, value])

    def on_headers_complete(self):
        if self._is_upgrade:
            return
        channels = {}
        self.message = self.get_message(
            self.transport, self.parser.get_http_version(),
            self.parser.get_method(), self.url, self.headers)
        channels['body'] = BodyChannel(self.transport)
        channels['reply'] = ReplyChannel(self)
        self.body_channel = channels['body']
        self._request_handler_task = self.loop.create_task(
            self.request_handler(self.message, channels))

    def on_body(self, body: bytes):
        if self._is_upgrade:
            return
        body_chunk = self.get_request_body_chunk(body, False, True)
        self._request_stream_task = self.loop.create_task(
            self.body_channel.send(body_chunk))

    def on_message_complete(self):
        if self._is_upgrade:
            return
        body_chunk = self.get_request_body_chunk(b'', False, False)
        self._request_stream_task = self.loop.create_task(
            self.body_channel.send(body_chunk))

    def get_request_body_chunk(self, content: bytes, closed: bool,
                               more_content: bool) -> Dict[str, Any]:
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#request-body-chunk
        '''
        return {
            'content': content,
            'closed': closed,
            'more_content': more_content
        }

    def get_message(self, transport, http_version: str, method: bytes,
                    url: bytes, headers: List[List[bytes]]) -> Dict[str, Any]:
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#request
        '''
        url_obj = parse_url(url)
        if url_obj.schema is None:
            if transport.get_extra_info('sslcontext'):
                scheme = 'https'
            else:
                scheme = 'http'
        else:
            scheme = url_obj.schema.decode()
        path = '' if url_obj.path is None else url_obj.path.decode('utf-8')
        query = b'' if url_obj.query is None else url_obj.query
        return {
            'channel': 'http.request',
            'reply_channel': None,
            'http_version': http_version,
            'method': method.decode(),
            'scheme': scheme,
            'path': path,
            'query_string': query,
            'root_path': '',
            'headers': headers,
            'body': b'',
            'body_channel': None,
            'client': transport.get_extra_info('peername'),
            'server': transport.get_extra_info('sockname')
        }

    def check_headers(self, headers: List[List[bytes]]) -> Dict[str, bool]:
        connection_close = False
        content_length = False
        for key, value in headers:
            if key == b'Connection' and value == b'close':
                connection_close = True
            if key == b'Content-Length':
                content_length = True
        return {
            'connection_close': connection_close,
            'content_length': content_length
        }

    def after_write(self, more_content, keep_alive):
        if not more_content and not keep_alive:
            self.transport.close()
        elif not more_content and keep_alive:
            self._last_request_time = self.get_current_time()
            self.cleanup()

    def is_response_chunk(self, message: Dict[str, Any]) -> bool:
        return 'status' not in message and 'headers' not in message

    def make_header_content(self, headers, result_headers,
                            content, more_content):
        header_content = b''
        if headers is not None:
            _header_content = []
            if not more_content and not result_headers['content_length']:
                _header_content.extend([b'Content-Length: ',
                                        str(len(content)).encode(), b'\r\n'])
            for key, value in headers:
                if key == b'Connection':
                    continue
                _header_content.extend([key, b': ', value, b'\r\n'])
            header_content = b''.join(_header_content)
        return header_content

    def send(self, message: Dict[str, Any]):
        transport = self.transport
        status = message.get('status')
        headers = message.get('headers')
        content = message.get('content')
        more_content = message.get('more_content', False)
        if headers is not None:
            result_headers = self.check_headers(headers)
            if result_headers['connection_close'] is True:
                self._keep_alive = False
        keep_alive = self.keep_alive

        if self.is_response_chunk(message):
            content_length = len(content)
            if more_content and content_length > 0:
                transport.write(b'%x\r\n%b\r\n' % (content_length, content))
                self.after_write(more_content, keep_alive)
            elif more_content is False:
                transport.write(b'0\r\n\r\n')
                self.after_write(more_content, keep_alive)
            return

        keep_alive_timeout = self.request_timeout
        timeout_header = b''
        if keep_alive and keep_alive_timeout is not None:
            timeout_header = b'Keep-Alive: %d\r\n' % keep_alive_timeout

        header_content = self.make_header_content(headers, result_headers,
                                                  content, more_content)

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
        self.after_write(more_content, keep_alive)

    def write_error(self, exception):
        try:
            request = None
            if self.message:
                request = self.request_class(self.message)
            response = self.error_handler.response(request, exception)
            self.send(response.get_message(False))
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
