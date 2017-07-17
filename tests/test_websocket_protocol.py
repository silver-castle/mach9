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
    assert message['channel'] == 'websocket.connect'
    assert message['reply_channel'] is None
    assert message['http_version'] == '1.1'
    assert message['method'] == 'GET'
    assert message['scheme'] == 'ws'
    assert message['query_string'] == b'key1=1&key2=2'
    assert message['root_path'] == ''
    assert message['order'] == 0
    assert message['headers'] == [[b'k1', b'v1']]
    assert message['client'] == ('127.0.0.1', 1234)
    assert message['server'] == ('127.0.0.1', 5678)
