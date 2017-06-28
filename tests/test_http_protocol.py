from mach9.http import HttpProtocol


def test_check_headers():
    protocol = HttpProtocol(loop=None, request_handler=None,
                            error_handler=None)
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
