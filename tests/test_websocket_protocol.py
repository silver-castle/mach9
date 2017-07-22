from mach9.http import HttpProtocol
from mach9.websocket import WebSocketProtocol
from tests.utils import Transport


def test_accept_content():
    http_protocol = HttpProtocol(loop=None, request_handler=None)
    headers = [[b'foo', b'bar']]
    websocket_protocol = WebSocketProtocol(http_protocol, headers)
    content = websocket_protocol.get_accept_content()
    output = b'HTTP/1.1 101 Switching Protocols\r\nfoo: bar\r\n\r\n'
    assert content == output


def test_get_connect_message():
    http_protocol = HttpProtocol(loop=None, request_handler=None)
    headers = [[b'foo', b'bar']]
    websocket_protocol = WebSocketProtocol(http_protocol, headers)
    transport = Transport()
    message = websocket_protocol.get_connect_message(
        transport,
        '1.1',
        b'GET',
        b'ws://127.0.0.1:1234/foo/bar?key1=1&key2=2',
        [[b'k1', b'v1']])
    assert websocket_protocol.order == 0
    assert message['channel'] == 'websocket.connect'
    assert message['reply_channel'] is None
    assert message['http_version'] == '1.1'
    assert message['method'] == 'GET'
    assert message['scheme'] == 'ws'
    assert message['query_string'] == b'key1=1&key2=2'
    assert message['root_path'] == ''
    assert message['path'] == '/foo/bar'
    assert message['order'] == 0
    assert message['headers'] == [[b'k1', b'v1']]
    assert message['client'] == ('127.0.0.1', 1234)
    assert message['server'] == ('127.0.0.1', 5678)


def test_get_receive_message():
    http_protocol = HttpProtocol(loop=None, request_handler=None)
    headers = [[b'foo', b'bar']]
    websocket_protocol = WebSocketProtocol(http_protocol, headers)
    transport = Transport()
    websocket_protocol.get_connect_message(
        transport,
        '1.1',
        b'GET',
        b'ws://127.0.0.1:1234/foo/bar?key1=1&key2=2',
        [[b'k1', b'v1']])
    message1 = websocket_protocol.get_receive_message('text')
    assert message1['channel'] == 'websocket.receive'
    assert message1['reply_channel'] is None
    assert message1['path'] == '/foo/bar'
    assert message1['order'] == 1
    assert message1['text'] == 'text'
    assert message1['bytes'] is None
    message2 = websocket_protocol.get_receive_message(b'bytes')
    assert message2['order'] == 2
    assert message2['text'] is None
    assert message2['bytes'] == b'bytes'


def test_get_disconnect_message():
    http_protocol = HttpProtocol(loop=None, request_handler=None)
    headers = [[b'foo', b'bar']]
    websocket_protocol = WebSocketProtocol(http_protocol, headers)
    transport = Transport()
    websocket_protocol.get_connect_message(
        transport,
        '1.1',
        b'GET',
        b'ws://127.0.0.1:1234/foo/bar?key1=1&key2=2',
        [[b'k1', b'v1']])
    websocket_protocol.order = 0
    message = websocket_protocol.get_disconnect_message(1000)
    assert message['channel'] == 'websocket.disconnect'
    assert message['reply_channel'] is None
    assert message['path'] == '/foo/bar'
    assert message['order'] == 1
    assert message['code'] == 1000
