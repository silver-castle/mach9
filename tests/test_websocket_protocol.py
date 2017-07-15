from mach9.http import HttpProtocol
from mach9.websocket import WebSocketProtocol


def test_accept_content():
    http_protocol = HttpProtocol(loop=None, request_handler=None)
    headers = [[b'foo', b'bar']]
    websocket_protocol = WebSocketProtocol(http_protocol, headers)
    content = websocket_protocol.get_accept_content()
    output = b'HTTP/1.1 101 Switching Protocols\r\nfoo: bar\r\n\r\n'
    assert content == output
