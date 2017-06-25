from cgi import parse_header
from collections import namedtuple
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlunparse
from ujson import loads as json_loads

from mach9.exceptions import InvalidUsage


DEFAULT_HTTP_CONTENT_TYPE = 'application/octet-stream'
# HTTP/1.1: https://www.w3.org/Protocols/rfc2616/rfc2616-sec7.html#sec7.2.1
# > If the media type remains unknown, the recipient SHOULD treat it
# > as type 'application/octet-stream'


class CIDict(dict):
    '''Case Insensitive dict where all keys are converted to lowercase
    This does not maintain the inputted case when calling items() or keys()
    in favor of speed, since headers are case insensitive
    '''

    def get(self, key, default=None):
        return super().get(key.casefold(), default)

    def __getitem__(self, key):
        return super().__getitem__(key.casefold())

    def __setitem__(self, key, value):
        return super().__setitem__(key.casefold(), value)

    def __contains__(self, key):
        return super().__contains__(key.casefold())


class RequestParameters(dict):
    '''Hosts a dict with lists as values where get returns the first
    value of the list and getlist returns the whole shebang
    '''

    def get(self, name, default=None):
        '''Return the first value, either the default or actual'''
        return super().get(name, [default])[0]

    def getlist(self, name, default=None):
        '''Return the entire list'''
        return super().get(name, default)


class Request(dict):
    '''Properties of an HTTP request such as URL, headers, etc.'''
    __slots__ = (
        'scheme', 'method', 'query_string', 'path',
        'app', 'headers', 'version', 'method', '_cookies',
        'body', 'parsed_json', 'parsed_args', 'parsed_form', 'parsed_files',
        'ip', '_parsed_url', 'uri_template', 'stream', '_invalid_usage'
    )

    def __init__(self, message, invalid_usage=None):
        # TODO: Content-Encoding detection
        self.app = None

        _headers = [(h[0].decode().casefold(), h[1].decode())
                    for h in message['headers']]
        self.headers = CIDict(_headers)
        self.scheme = message['scheme']
        self.method = message['method']
        self.version = message['http_version']
        self.query_string = message['query_string'].decode('utf-8')
        self.path = message['path']
        self.ip = message['server']

        # Init but do not inhale
        self.body = b''
        self.parsed_json = None
        self.parsed_form = None
        self.parsed_files = None
        self.parsed_args = None
        self.uri_template = None
        self.stream = None
        self._cookies = None
        self._invalid_usage = invalid_usage or InvalidUsage

    @property
    def args(self):
        if self.parsed_args is None:
            if self.query_string:
                self.parsed_args = RequestParameters(
                    parse_qs(self.query_string))
            else:
                self.parsed_args = RequestParameters()
        return self.parsed_args

    @property
    def json(self):
        if self.parsed_json is None:
            try:
                self.parsed_json = json_loads(self.body)
            except Exception:
                if not self.body:
                    return None
                raise self._invalid_usage('Failed when parsing body as json')

        return self.parsed_json

    @property
    def token(self):
        '''Attempt to return the auth header token.

        :return: token related to request
        '''
        auth_header = self.headers.get('Authorization', '')
        if 'Token ' in auth_header:
            return auth_header.partition('Token ')[-1]
        else:
            return auth_header

    @property
    def form(self):
        if self.parsed_form is None:
            self.parsed_form = RequestParameters()
            self.parsed_files = RequestParameters()
            content_type = self.headers.get(
                'Content-Type', DEFAULT_HTTP_CONTENT_TYPE)
            content_type, parameters = parse_header(content_type)
            try:
                if content_type == 'application/x-www-form-urlencoded':
                    self.parsed_form = RequestParameters(
                        parse_qs(self.body.decode('utf-8')))
                elif content_type == 'multipart/form-data':
                    # TODO: Stream this instead of reading to/from memory
                    boundary = parameters['boundary'].encode('utf-8')
                    self.parsed_form, self.parsed_files = (
                        parse_multipart_form(self.body, boundary))
            except Exception:
                self.app.log.exception('Failed when parsing form')

        return self.parsed_form

    @property
    def files(self):
        if self.parsed_files is None:
            self.form  # compute form to get files

        return self.parsed_files

    @property
    def raw_args(self):
        return {k: v[0] for k, v in self.args.items()}

    @property
    def cookies(self):
        if self._cookies is None:
            cookie = self.headers.get('cookie')
            if cookie is not None:
                cookies = SimpleCookie()
                cookies.load(cookie)
                self._cookies = {name: cookie.value
                                 for name, cookie in cookies.items()}
            else:
                self._cookies = {}
        return self._cookies

    @property
    def host(self):
        # it appears that httptools doesn't return the host
        # so pull it from the headers
        return self.headers.get('Host', '')

    @property
    def url(self):
        return urlunparse((
            self.scheme,
            self.host,
            self.path,
            None,
            self.query_string,
            None))


File = namedtuple('File', ['type', 'body', 'name'])


def parse_multipart_form(body, boundary):
    '''Parse a request body and returns fields and files

    :param body: bytes request body
    :param boundary: bytes multipart boundary
    :return: fields (RequestParameters), files (RequestParameters)
    '''
    files = RequestParameters()
    fields = RequestParameters()

    form_parts = body.split(boundary)
    for form_part in form_parts[1:-1]:
        file_name = None
        file_type = None
        field_name = None
        line_index = 2
        line_end_index = 0
        while not line_end_index == -1:
            line_end_index = form_part.find(b'\r\n', line_index)
            form_line = form_part[line_index:line_end_index].decode('utf-8')
            line_index = line_end_index + 2

            if not form_line:
                break

            colon_index = form_line.index(':')
            form_header_field = form_line[0:colon_index]
            form_header_value, form_parameters = parse_header(
                form_line[colon_index + 2:])

            if form_header_field == 'Content-Disposition':
                if 'filename' in form_parameters:
                    file_name = form_parameters['filename']
                field_name = form_parameters.get('name')
            elif form_header_field == 'Content-Type':
                file_type = form_header_value

        post_data = form_part[line_index:-4]
        if file_name or file_type:
            file = File(type=file_type, name=file_name, body=post_data)
            if field_name in files:
                files[field_name].append(file)
            else:
                files[field_name] = [file]
        else:
            value = post_data.decode('utf-8')
            if field_name in fields:
                fields[field_name].append(value)
            else:
                fields[field_name] = [value]

    return fields, files
