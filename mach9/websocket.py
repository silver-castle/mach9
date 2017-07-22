import websockets
from websockets.protocol import WebSocketCommonProtocol
from httptools import parse_url
from typing import List


class ReplyChannel:
    def __init__(self, websocket_protocol):
        self._websocket_protocol = websocket_protocol
        self._accept = False
        self.name = 'reply:%d' % id(self)

    async def send(self, message):
        if not self._accept:
            self._accept = message.get('accept')
            if not self._accept:
                self._websocket_protocol.close()
                return
            accept_content = self._websocket_protocol.get_accept_content()
            self._websocket_protocol.transport.write(accept_content)
            self._websocket_protocol.loop.create_task(
                self._websocket_protocol.read())
        if message.get('text'):
            await self._websocket_protocol.send(message['text'])
        elif message.get('bytes'):
            await self._websocket_protocol.send(message['bytes'])
        if message.get('close'):
            self._websocket_protocol.close()


class WebSocketProtocol(WebSocketCommonProtocol):
    def __init__(self, http_protocol, response_headers: List[List[bytes]],
                 max_size=1000000, max_queue=100000):
        super().__init__(max_size=max_size, max_queue=max_queue,
                         loop=http_protocol.loop)
        self.request_handler = http_protocol.request_handler
        self.transport = http_protocol.transport
        self.response_headers = response_headers
        self.channels = {
            'reply': ReplyChannel(self)
        }

    def cleanup(self):
        self.request_handler = None
        self.transport = None
        self.response_headers = None
        self.channels = None

    def get_accept_content(self):
        content = b'HTTP/1.1 101 Switching Protocols\r\n'
        for key, value in self.response_headers:
            content += key + b': ' + value + b'\r\n'
        content += b'\r\n'
        return content

    def get_connect_message(self, transport, http_version, method, url,
                            headers):
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#connection
        '''
        url_obj = parse_url(url)
        if url_obj.schema is None:
            if transport.get_extra_info('sslcontext'):
                scheme = 'wss'
            else:
                scheme = 'ws'
        else:
            scheme = url_obj.schema.decode()
        self.path = ('' if url_obj.path is None
                     else url_obj.path.decode('utf-8'))
        query = b'' if url_obj.query is None else url_obj.query
        self.order = 0
        return {
            'channel': 'websocket.connect',
            'reply_channel': None,
            'http_version': http_version,
            'method': method.decode(),
            'scheme': scheme,
            'path': self.path,
            'query_string': query,
            'root_path': '',
            'headers': headers,
            'client': transport.get_extra_info('peername'),
            'server': transport.get_extra_info('sockname'),
            'order': self.order,
        }

    def get_receive_message(self, data):
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#receive
        '''
        self.order += 1
        message = {
            'channel': 'websocket.receive',
            'reply_channel': None,
            'path': self.path,
            'order': self.order,
            'text': None,
            'bytes': None,
        }
        if isinstance(data, str):
            message['text'] = data
        elif isinstance(data, bytes):
            message['bytes'] = data
        return message

    def get_disconnect_message(self, code: int):
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#disconnection
        '''
        self.order += 1
        return {
            'channel': 'websocket.disconnect',
            'reply_channel': None,
            'path': self.path,
            'order': self.order,
            'code': code,
        }

    async def read(self):
        code = None
        while True:
            try:
                data = await self.recv()
            except websockets.exceptions.ConnectionClosed as e:
                code = e.code
                break
            message = self.get_receive_message(data)
            self.loop.create_task(self.request_handler(message, self.channels))
        message = self.get_disconnect_message(code)
        self.loop.create_task(self.request_handler(message, self.channels))
        self.cleanup()

    def connection_made(self, transport, http_version, method, url, headers):
        super().connection_made(transport)
        message = self.get_connect_message(transport, http_version, method,
                                           url, headers)
        self.loop.create_task(self.request_handler(message, self.channels))


def upgrade_to_websocket(http_protocol):
    request_headers = dict(http_protocol.headers)
    response_headers = []

    def get_header(key):
        key = key.lower().encode('utf-8')
        return request_headers.get(key, b'').decode('utf-8')

    def set_header(key, value):
        response_headers.append((key.encode('utf-8'), value.encode('utf-8')))

    try:
        key = websockets.handshake.check_request(get_header)
        websockets.handshake.build_response(set_header, key)
    except websockets.InvalidHandshake:
        http_protocol.send({
            'status': 400,
            'headers': [[b'Content-Type', b'text/plain']],
            'content': b'Invalid Handshake'})
    websocket = WebSocketProtocol(http_protocol, response_headers)
    websocket.connection_made(http_protocol.transport,
                              http_protocol.parser.get_http_version(),
                              http_protocol.parser.get_method(),
                              http_protocol.url,
                              http_protocol.headers)
    http_protocol.transport.set_protocol(websocket)
