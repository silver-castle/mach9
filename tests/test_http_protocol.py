from mach9.http import HttpProtocol


class Transport:

    def get_extra_info(self, name):
        if name == 'peername':
            return ('127.0.0.1', 1234)
        elif name == 'sockname':
            return ('127.0.0.1', 5678)


def test_check_headers():
    protocol = HttpProtocol(loop=None, request_handler=None)
    result_headers = protocol.check_headers([])
    assert result_headers['connection_close'] is False
    assert result_headers['content_length'] is False

    result_headers = protocol.check_headers([
        [b'Connection', b'close'],
        [b'Content-Length', b'1'],
    ])
    assert result_headers['connection_close'] is True
    assert result_headers['content_length'] is True

    result_headers = protocol.check_headers([
        [b'Connection', b'__close'],
        [b'_Content-Length', b'1'],
    ])
    assert result_headers['connection_close'] is False
    assert result_headers['content_length'] is False

    result_headers = protocol.check_headers([
        [b'__Connection', b'close'],
        [b'Content-Length', b'1'],
    ])
    assert result_headers['connection_close'] is False
    assert result_headers['content_length'] is True


def test_is_reponse_chunk():
    protocol = HttpProtocol(loop=None, request_handler=None)
    result = protocol.is_response_chunk({'a': 1})
    assert result is True
    result = protocol.is_response_chunk({'status': 1})
    assert result is False
    result = protocol.is_response_chunk({'headers': 1})
    assert result is False
    result = protocol.is_response_chunk({'status': 1, 'headers': 1})
    assert result is False


def test_make_header_content():
    protocol = HttpProtocol(loop=None, request_handler=None)
    result_headers = {
        'connection_close': False,
        'content_length': False
    }
    header_content = protocol.make_header_content(
        None, result_headers, b'123', False)
    assert header_content == b''

    result_headers = {
        'connection_close': False,
        'content_length': False
    }
    header_content = protocol.make_header_content(
        [], result_headers, b'123', False)
    assert header_content == b'Content-Length: 3\r\n'

    result_headers = {
        'connection_close': False,
        'content_length': False
    }
    header_content = protocol.make_header_content(
        [], result_headers, b'123', True)
    assert header_content == b''

    result_headers = {
        'connection_close': False,
        'content_length': True
    }
    header_content = protocol.make_header_content(
        [], result_headers, b'123', False)
    assert header_content == b''

    result_headers = {
        'connection_close': True,
        'content_length': True
    }
    header_content = protocol.make_header_content(
        [[b'Connection', b'1']], result_headers, b'123', False)
    assert header_content == b''

    result_headers = {
        'connection_close': False,
        'content_length': True
    }
    header_content = protocol.make_header_content(
        [[b'Connection', b'1']], result_headers, b'123', False)
    assert header_content == b''

    result_headers = {
        'connection_close': False,
        'content_length': False
    }
    header_content = protocol.make_header_content(
        [[b'foo', b'bar']], result_headers, b'123', False)
    assert header_content == b'Content-Length: 3\r\nfoo: bar\r\n'


def get_request_body_chunk():
    http_protocol = HttpProtocol(loop=None, request_handler=None,)
    message = http_protocol.get_request_body_chunk(b'foo', False, True)
    message['content'] = b'foo'
    message['closed'] = False
    message['more_content'] = True


def test_get_message():
    http_protocol = HttpProtocol(loop=None, request_handler=None)
    transport = Transport()
    message = http_protocol.get_message(
        transport,
        '1.1',
        b'GET',
        b'http://127.0.0.1:1234/foo/bar?key1=1&key2=2',
        [[b'k1', 'v1']])
    assert message['channel'] == 'http.request'
    assert message['reply_channel'] is None
    assert message['http_version'] == '1.1'
    assert message['method'] == 'GET'
    assert message['scheme'] == 'http'
    assert message['query_string'] == b'key1=1&key2=2'
    assert message['root_path'] == ''
    assert message['headers'] == [[b'k1', 'v1']]
    assert message['body'] == b''
    assert message['body_channel'] is None
    assert message['client'] == ('127.0.0.1', 1234)
    assert message['server'] == ('127.0.0.1', 5678)
