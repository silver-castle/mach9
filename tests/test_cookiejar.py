from mach9.response import CookieJar, MultiHeader, Cookie


def test_set():
    cookie_jar = CookieJar({})
    assert isinstance(cookie_jar.headers, dict)
    cookie_jar['a'] = '1'
    cookie_header = cookie_jar.cookie_headers['a']
    assert isinstance(cookie_header, MultiHeader)
    assert cookie_header.name == 'Set-Cookie'
    cookie_jar['b'] = '2'
    multi_headers = list(cookie_jar.headers.keys())
    assert len(multi_headers) == 2
    cookies = list(cookie_jar.headers.values())
    assert len(cookies) == 2
    for header in multi_headers:
        assert isinstance(header, MultiHeader)
        assert header.name == 'Set-Cookie'
        assert header.encode() == b'Set-Cookie'
    for cookie in cookies:
        assert isinstance(cookie, Cookie)
    cookie_keys = sorted(list(map(lambda c: c.key, cookies)))
    assert cookie_keys == ['a', 'b']
    cookie_values = sorted(list(map(lambda c: c.value, cookies)))
    assert cookie_values == ['1', '2']
    assert cookie_jar['a']['path'] == '/'


def test_del():
    cookie_jar = CookieJar({})
    del cookie_jar['a']
    assert isinstance(cookie_jar['a'], Cookie)
    assert cookie_jar['a']['max-age'] == 0
