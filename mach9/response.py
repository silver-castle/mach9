import re
import string
from mimetypes import guess_type
from os import path
from ujson import dumps as json_dumps
from aiofiles import open as open_async

COMMON_STATUS_CODES = {
    200: b'OK',
    400: b'Bad Request',
    404: b'Not Found',
    500: b'Internal Server Error',
}
ALL_STATUS_CODES = {
    100: b'Continue',
    101: b'Switching Protocols',
    102: b'Processing',
    200: b'OK',
    201: b'Created',
    202: b'Accepted',
    203: b'Non-Authoritative Information',
    204: b'No Content',
    205: b'Reset Content',
    206: b'Partial Content',
    207: b'Multi-Status',
    208: b'Already Reported',
    226: b'IM Used',
    300: b'Multiple Choices',
    301: b'Moved Permanently',
    302: b'Found',
    303: b'See Other',
    304: b'Not Modified',
    305: b'Use Proxy',
    307: b'Temporary Redirect',
    308: b'Permanent Redirect',
    400: b'Bad Request',
    401: b'Unauthorized',
    402: b'Payment Required',
    403: b'Forbidden',
    404: b'Not Found',
    405: b'Method Not Allowed',
    406: b'Not Acceptable',
    407: b'Proxy Authentication Required',
    408: b'Request Timeout',
    409: b'Conflict',
    410: b'Gone',
    411: b'Length Required',
    412: b'Precondition Failed',
    413: b'Request Entity Too Large',
    414: b'Request-URI Too Long',
    415: b'Unsupported Media Type',
    416: b'Requested Range Not Satisfiable',
    417: b'Expectation Failed',
    422: b'Unprocessable Entity',
    423: b'Locked',
    424: b'Failed Dependency',
    426: b'Upgrade Required',
    428: b'Precondition Required',
    429: b'Too Many Requests',
    431: b'Request Header Fields Too Large',
    500: b'Internal Server Error',
    501: b'Not Implemented',
    502: b'Bad Gateway',
    503: b'Service Unavailable',
    504: b'Gateway Timeout',
    505: b'HTTP Version Not Supported',
    506: b'Variant Also Negotiates',
    507: b'Insufficient Storage',
    508: b'Loop Detected',
    510: b'Not Extended',
    511: b'Network Authentication Required'
}


# ------------------------------------------------------------ #
#  SimpleCookie
# ------------------------------------------------------------ #

# Straight up copied this section of dark magic from SimpleCookie

_LegalChars = string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~:"
_UnescapedChars = _LegalChars + ' ()/<=>?@[]{}'

_Translator = {n: '\\%03o' % n
               for n in set(range(256)) - set(map(ord, _UnescapedChars))}
_Translator.update({
    ord('"'): '\\"',
    ord('\\'): '\\\\',
})


def _quote(s):
    '''Quote a string for use in a cookie header.
    If the string does not need to be double-quoted, then just return the
    string.  Otherwise, surround the string in doublequotes and quote
    (with a \) special characters.
    '''
    if s is None or _is_legal_key(s):
        return s
    else:
        return '"' + s.translate(_Translator) + '"'


_is_legal_key = re.compile('[%s]+' % re.escape(_LegalChars)).fullmatch

# ------------------------------------------------------------ #
#  Custom SimpleCookie
# ------------------------------------------------------------ #


class CookieJar(dict):
    '''CookieJar dynamically writes headers as cookies are added and removed
    It gets around the limitation of one header per name by using the
    MultiHeader class to provide a unique key that encodes to Set-Cookie.
    '''

    def __init__(self, headers):
        super().__init__()
        self.headers = headers
        self.cookie_headers = {}

    def __setitem__(self, key, value):
        # If this cookie doesn't exist, add it to the header keys
        cookie_header = self.cookie_headers.get(key)
        if not cookie_header:
            cookie = Cookie(key, value)
            cookie['path'] = '/'
            cookie_header = MultiHeader('Set-Cookie')
            self.cookie_headers[key] = cookie_header
            self.headers[cookie_header] = cookie
            super().__setitem__(key, cookie)
        else:
            self[key].value = value

    def __delitem__(self, key):
        if key not in self.cookie_headers:
            self[key] = ''
            self[key]['max-age'] = 0
        else:
            cookie_header = self.cookie_headers[key]
            del self.headers[cookie_header]
            del self.cookie_headers[key]
            super().__delitem__(key)


class Cookie(dict):
    '''A stripped down version of Morsel from SimpleCookie #gottagofast'''
    _keys = {
        'expires': 'expires',
        'path': 'Path',
        'comment': 'Comment',
        'domain': 'Domain',
        'max-age': 'Max-Age',
        'secure': 'Secure',
        'httponly': 'HttpOnly',
        'version': 'Version',
    }
    _flags = {'secure', 'httponly'}

    def __init__(self, key, value):
        if key in self._keys:
            raise KeyError('Cookie name is a reserved word')
        if not _is_legal_key(key):
            raise KeyError('Cookie key contains illegal characters')
        self.key = key
        self.value = value
        super().__init__()

    def __setitem__(self, key, value):
        if key not in self._keys:
            raise KeyError('Unknown cookie property')
        super().__setitem__(key, value)

    def encode(self, encoding):
        output = ['%s=%s' % (self.key, _quote(self.value))]
        for key, value in self.items():
            if key == 'max-age':
                try:
                    output.append('%s=%d' % (self._keys[key], value))
                except TypeError:
                    output.append('%s=%s' % (self._keys[key], value))
            elif key == 'expires':
                try:
                    output.append('%s=%s' % (
                        self._keys[key],
                        value.strftime('%a, %d-%b-%Y %T GMT')
                    ))
                except AttributeError:
                    output.append('%s=%s' % (self._keys[key], value))
            elif key in self._flags:
                if self[key]:
                    output.append(self._keys[key])
            else:
                output.append('%s=%s' % (self._keys[key], value))

        return '; '.join(output).encode(encoding)

# ------------------------------------------------------------ #
#  Header Trickery
# ------------------------------------------------------------ #


class MultiHeader:
    '''String-holding object which allow us to set a header within response
    that has a unique key, but may contain duplicate header names
    '''
    def __init__(self, name):
        self.name = name

    def encode(self):
        return self.name.encode()


class HTTPResponse:
    __slots__ = ('body', 'status', 'content_type', 'headers', '_cookies')

    def __init__(self, body=None, status=200, headers=None,
                 content_type='text/plain', body_bytes=b''):
        if body is not None:
            self.body = self._encode_body(body)
        else:
            self.body = body_bytes
        self.status = status
        self.headers = headers or {}
        self._cookies = None
        self.content_type = content_type
        self.headers['Content-Type'] = self.headers.get(
            'Content-Type', self.content_type)

    @property
    def cookies(self):
        if self._cookies is None:
            self._cookies = CookieJar(self.headers)
        return self._cookies

    def _encode_body(self, data):
        try:
            # Try to encode it regularly
            return data.encode()
        except AttributeError:
            # Convert it to a str if you can't
            return str(data).encode()

    def _parse_headers(self):
        headers = []
        for name, value in self.headers.items():
            try:
                headers.append([name.encode(), value.encode('utf-8')])
            except AttributeError:
                headers.append(
                    [str(name).encode(), str(value).encode('utf-8')])
        return headers

    def get_message(self, more_content):
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#response
        '''
        return {
            'status': self.status,
            'content': self.body,
            'headers': self._parse_headers(),
            'more_content': more_content
        }

    def get_response_chunk(self, content, more_content):
        '''
        http://channels.readthedocs.io/en/stable/asgi/www.html#response-chunk
        '''
        return {
            'content': content,
            'more_content': more_content
        }

    def output(
            self, version='1.1', keep_alive=False, keep_alive_timeout=None):
        # This is all returned in a kind-of funky way
        # We tried to make this as fast as possible in pure python
        timeout_header = b''
        if keep_alive and keep_alive_timeout is not None:
            timeout_header = b'Keep-Alive: %d\r\n' % keep_alive_timeout
        self.headers['Content-Length'] = self.headers.get(
            'Content-Length', len(self.body))
        self.headers['Content-Type'] = self.headers.get(
            'Content-Type', self.content_type)

        headers = self._parse_headers()

        # Try to pull from the common codes first
        # Speeds up response rate 6% over pulling from all
        status = COMMON_STATUS_CODES.get(self.status)
        if not status:
            status = ALL_STATUS_CODES.get(self.status, b'UNKNOWN RESPONSE')

        return (b'HTTP/%b %d %b\r\n'
                b'Connection: %b\r\n'
                b'%b'
                b'%b\r\n'
                b'%b') % (
                   version.encode(),
                   self.status,
                   status,
                   b'keep-alive' if keep_alive else b'close',
                   timeout_header,
                   headers,
                   self.body
               )


def json(body, status=200, headers=None, **kwargs):
    '''
    Returns response object with body in json format.
    :param body: Response data to be serialized.
    :param status: Response code.
    :param headers: Custom Headers.
    :param kwargs: Remaining arguments that are passed to the json encoder.
    '''
    return HTTPResponse(json_dumps(body, **kwargs), headers=headers,
                        status=status, content_type='application/json')


def text(body, status=200, headers=None,
         content_type='text/plain; charset=utf-8'):
    '''
    Returns response object with body in text format.
    :param body: Response data to be encoded.
    :param status: Response code.
    :param headers: Custom Headers.
    :param content_type: the content type (string) of the response
    '''
    return HTTPResponse(
        body, status=status, headers=headers,
        content_type=content_type)


def raw(body, status=200, headers=None,
        content_type='application/octet-stream'):
    '''
    Returns response object without encoding the body.
    :param body: Response data.
    :param status: Response code.
    :param headers: Custom Headers.
    :param content_type: the content type (string) of the response.
    '''
    return HTTPResponse(body_bytes=body, status=status, headers=headers,
                        content_type=content_type)


def html(body, status=200, headers=None):
    '''
    Returns response object with body in html format.
    :param body: Response data to be encoded.
    :param status: Response code.
    :param headers: Custom Headers.
    '''
    return HTTPResponse(body, status=status, headers=headers,
                        content_type='text/html; charset=utf-8')


async def file(location, mime_type=None, headers=None, _range=None):
    '''Return a response object with file data.

    :param location: Location of file on system.
    :param mime_type: Specific mime_type.
    :param headers: Custom Headers.
    :param _range:
    '''
    filename = path.split(location)[-1]

    async with open_async(location, mode='rb') as _file:
        if _range:
            await _file.seek(_range.start)
            out_stream = await _file.read(_range.size)
            headers['Content-Range'] = 'bytes %s-%s/%s' % (
                _range.start, _range.end, _range.total)
        else:
            out_stream = await _file.read()

    mime_type = mime_type or guess_type(filename)[0] or 'text/plain'

    return HTTPResponse(status=200,
                        headers=headers,
                        content_type=mime_type,
                        body_bytes=out_stream)


def redirect(to, headers=None, status=302,
             content_type='text/html; charset=utf-8'):
    '''Abort execution and cause a 302 redirect (by default).

    :param to: path or fully qualified URL to redirect to
    :param headers: optional dict of headers to include in the new request
    :param status: status code (int) of the new request, defaults to 302
    :param content_type: the content type (string) of the response
    :returns: the redirecting Response
    '''
    headers = headers or {}

    # According to RFC 7231, a relative URI is now permitted.
    headers['Location'] = to

    return HTTPResponse(
        status=status,
        headers=headers,
        content_type=content_type)
