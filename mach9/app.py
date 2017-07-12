import logging
import logging.config
import re
from asyncio import get_event_loop, Queue
from collections import deque, defaultdict
from functools import partial
from inspect import isawaitable, stack, getmodulename
from traceback import format_exc
from urllib.parse import urlencode, urlunparse

from mach9.config import Config, LOGGING
from mach9.exceptions import ServerError, URLBuildError
from mach9.handlers import ErrorHandler
from mach9.log import log as _log
from mach9.log import log as _netlog
from mach9.response import HTTPResponse, StreamHTTPResponse, WebsocketResponse
from mach9.router import Router
from mach9.request import Request
from mach9.static import register as static_register
from mach9.testing import Mach9TestClient
from mach9.views import CompositionView
from mach9.server import Server


class Mach9:

    def __init__(self, name=None, router=None, error_handler=None,
                 load_env=True, request_class=None, debug=None,
                 log=None, netlog=None,
                 log_config=LOGGING,
                 get_current_time=None, composition_view=None,
                 stream_http_response_class=None,
                 websocket_response_class=None):

        self.log = log or _log

        if log_config:
            logging.config.dictConfig(log_config)
        # Only set up a default log handler if the
        # end-user application didn't set anything up.
        if (log_config and not logging.root.handlers
                and self.log.level == logging.NOTSET):
            formatter = logging.Formatter(
                '%(asctime)s: %(levelname)s: %(message)s')
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            self.log.addHandler(handler)
            self.log.setLevel(logging.INFO)

        # Get name from previous stack frame
        if name is None:
            frame_records = stack()[1]
            name = getmodulename(frame_records[1])

        _composition_view = composition_view or CompositionView

        self.config = config = Config(load_env=load_env)
        self.request_max_size = config.REQUEST_MAX_SIZE
        self.request_timeout = config.REQUEST_TIMEOUT
        self.keep_alive = config.KEEP_ALIVE
        self.name = name
        self.websocket_channels = {}
        self.composition_view_class = _composition_view
        self.router = router or Router(_composition_view)
        self.request_class = request_class or Request
        self.error_handler = error_handler or ErrorHandler(self.log)
        self.debug = debug
        self.error_handler.debug = debug
        self.log_config = log_config
        self.request_middleware = deque()
        self.response_middleware = deque()
        self.blueprints = {}
        self._blueprint_order = []
        self.stream_http_response_class = (
            stream_http_response_class or StreamHTTPResponse)
        self.websocket_response_class = (
            websocket_response_class or WebsocketResponse)
        self.sock = None
        self.listeners = defaultdict(list)
        self.is_running = False
        self.netlog = netlog or _netlog

    @property
    def loop(self):
        return get_event_loop()

    # -------------------------------------------------------------------- #
    # Registration
    # -------------------------------------------------------------------- #

    # Decorator
    def listener(self, event):
        '''Create a listener from a decorated function.

        :param event: event to listen to
        '''
        def decorator(listener):
            self.listeners[event].append(listener)
            return listener
        return decorator

    # Decorator
    def route(self, uri, methods=frozenset({'GET'}), host=None,
              strict_slashes=False, stream=False, websocket=False):
        '''Decorate a function to be registered as a route

        :param uri: path of the URL
        :param methods: list or tuple of methods allowed
        :param host:
        :param strict_slashes:
        :param stream:
        :return: decorated function
        '''

        # Fix case where the user did not prefix the URL with a /
        # and will probably get confused as to why it's not working
        if not uri.startswith('/'):
            uri = '/' + uri

        def response(handler):
            if websocket:
                handler.is_websocket = True
            elif stream:
                handler.is_stream = True
            self.router.add(uri=uri, methods=methods, handler=handler,
                            host=host, strict_slashes=strict_slashes)
            return handler

        return response

    # Shorthand method decorators
    def get(self, uri, host=None, strict_slashes=False, websocket=False):
        return self.route(uri, methods=frozenset({'GET'}), host=host,
                          strict_slashes=strict_slashes, websocket=websocket)

    def post(self, uri, host=None, strict_slashes=False, stream=False):
        return self.route(uri, methods=frozenset({'POST'}), host=host,
                          strict_slashes=strict_slashes, stream=stream)

    def put(self, uri, host=None, strict_slashes=False, stream=False):
        return self.route(uri, methods=frozenset({'PUT'}), host=host,
                          strict_slashes=strict_slashes, stream=stream)

    def head(self, uri, host=None, strict_slashes=False):
        return self.route(uri, methods=frozenset({'HEAD'}), host=host,
                          strict_slashes=strict_slashes)

    def options(self, uri, host=None, strict_slashes=False):
        return self.route(uri, methods=frozenset({'OPTIONS'}), host=host,
                          strict_slashes=strict_slashes)

    def patch(self, uri, host=None, strict_slashes=False, stream=False):
        return self.route(uri, methods=frozenset({'PATCH'}), host=host,
                          strict_slashes=strict_slashes, stream=stream)

    def delete(self, uri, host=None, strict_slashes=False):
        return self.route(uri, methods=frozenset({'DELETE'}), host=host,
                          strict_slashes=strict_slashes)

    def add_route(self, handler, uri, methods=frozenset({'GET'}), host=None,
                  strict_slashes=False):
        '''A helper method to register class instance or
        functions as a handler to the application url
        routes.

        :param handler: function or class instance
        :param uri: path of the URL
        :param methods: list or tuple of methods allowed, these are overridden
                        if using a HTTPMethodView
        :param host:
        :return: function or class instance
        '''
        stream = False
        # Handle HTTPMethodView differently
        if hasattr(handler, 'view_class'):
            http_methods = (
                'GET', 'POST', 'PUT', 'HEAD', 'OPTIONS', 'PATCH', 'DELETE')
            methods = set()
            for method in http_methods:
                _handler = getattr(handler.view_class, method.lower(), None)
                if _handler:
                    methods.add(method)
                    if hasattr(_handler, 'is_stream'):
                        stream = True

        # handle composition view differently
        if isinstance(handler, self.composition_view_class):
            methods = handler.handlers.keys()
            for _handler in handler.handlers.values():
                if hasattr(_handler, 'is_stream'):
                    stream = True
                    break

        self.route(uri=uri, methods=methods, host=host,
                   strict_slashes=strict_slashes, stream=stream)(handler)
        return handler

    def remove_route(self, uri, clean_cache=True, host=None):
        self.router.remove(uri, clean_cache, host)

    # Decorator
    def exception(self, *exceptions):
        '''Decorate a function to be registered as a handler for exceptions

        :param exceptions: exceptions
        :return: decorated function
        '''

        def response(handler):
            for exception in exceptions:
                if isinstance(exception, (tuple, list)):
                    for e in exception:
                        self.error_handler.add(e, handler)
                else:
                    self.error_handler.add(exception, handler)
            return handler

        return response

    # Decorator
    def middleware(self, middleware_or_request):
        '''Decorate and register middleware to be called before a request.
        Can either be called as @app.middleware or @app.middleware('request')
        '''
        def register_middleware(middleware, attach_to='request'):
            if attach_to == 'request':
                self.request_middleware.append(middleware)
            if attach_to == 'response':
                self.response_middleware.appendleft(middleware)
            return middleware

        # Detect which way this was called, @middleware or @middleware('AT')
        if callable(middleware_or_request):
            return register_middleware(middleware_or_request)

        else:
            return partial(register_middleware,
                           attach_to=middleware_or_request)

    # Static Files
    def static(self, uri, file_or_directory, pattern=r'/?.+',
               use_modified_since=True, use_content_range=False):
        '''Register a root to serve files from. The input can either be a
        file or a directory. See
        '''
        static_register(self, uri, file_or_directory, pattern,
                        use_modified_since, use_content_range)

    def blueprint(self, blueprint, **options):
        '''Register a blueprint on the application.

        :param blueprint: Blueprint object
        :param options: option dictionary with blueprint defaults
        :return: Nothing
        '''
        if blueprint.name in self.blueprints:
            assert self.blueprints[blueprint.name] is blueprint, \
                'A blueprint with the name "%s" is already registered.  ' \
                'Blueprint names must be unique.' % \
                (blueprint.name,)
        else:
            self.blueprints[blueprint.name] = blueprint
            self._blueprint_order.append(blueprint)
        blueprint.register(self, options)

    def url_for(self, view_name: str, **kwargs):
        '''Build a URL based on a view name and the values provided.

        In order to build a URL, all request parameters must be supplied as
        keyword arguments, and each parameter must pass the test for the
        specified parameter type. If these conditions are not met, a
        `URLBuildError` will be thrown.

        Keyword arguments that are not request parameters will be included in
        the output URL's query string.

        :param view_name: string referencing the view name
        :param \*\*kwargs: keys and values that are used to build request
            parameters and query string arguments.

        :return: the built URL

        Raises:
            URLBuildError
        '''
        # find the route by the supplied view name
        uri, route = self.router.find_route_by_view_name(view_name)

        if not uri or not route:
            raise URLBuildError(
                    'Endpoint with name `{}` was not found'.format(
                        view_name))

        if uri != '/' and uri.endswith('/'):
            uri = uri[:-1]

        out = uri

        # find all the parameters we will need to build in the URL
        matched_params = re.findall(
            self.router.parameter_pattern, uri)

        # _method is only a placeholder now, don't know how to support it
        kwargs.pop('_method', None)
        anchor = kwargs.pop('_anchor', '')
        # _external need SERVER_NAME in config or pass _server arg
        external = kwargs.pop('_external', False)
        scheme = kwargs.pop('_scheme', '')
        if scheme and not external:
            raise ValueError('When specifying _scheme, _external must be True')

        netloc = kwargs.pop('_server', None)
        if netloc is None and external:
            netloc = self.config.get('SERVER_NAME', '')

        for match in matched_params:
            name, _type, pattern = self.router.parse_parameter_string(
                match)
            # we only want to match against each individual parameter
            specific_pattern = '^{}$'.format(pattern)
            supplied_param = None

            if kwargs.get(name):
                supplied_param = kwargs.get(name)
                del kwargs[name]
            else:
                raise URLBuildError(
                    'Required parameter `{}` was not passed to url_for'.format(
                        name))

            supplied_param = str(supplied_param)
            # determine if the parameter supplied by the caller passes the test
            # in the URL
            passes_pattern = re.match(specific_pattern, supplied_param)

            if not passes_pattern:
                if _type != str:
                    msg = (
                        'Value "{}" for parameter `{}` does not '
                        'match pattern for type `{}`: {}'.format(
                            supplied_param, name, _type.__name__, pattern))
                else:
                    msg = (
                        'Value "{}" for parameter `{}` '
                        'does not satisfy pattern {}'.format(
                            supplied_param, name, pattern))
                raise URLBuildError(msg)

            # replace the parameter in the URL with the supplied value
            replacement_regex = '(<{}.*?>)'.format(name)

            out = re.sub(
                replacement_regex, supplied_param, out)

        # parse the remainder of the keyword arguments into a querystring
        query_string = urlencode(kwargs, doseq=True) if kwargs else ''
        # scheme://netloc/path;parameters?query#fragment
        out = urlunparse((scheme, netloc, out, '', query_string, anchor))

        return out

    # -------------------------------------------------------------------- #
    # Testing
    # -------------------------------------------------------------------- #

    @property
    def test_client(self):
        return Mach9TestClient(self)

    # -------------------------------------------------------------------- #
    # Execution
    # -------------------------------------------------------------------- #

    async def _run_request_middleware(self, request):
        # The if improves speed.  I don't know why
        if self.request_middleware:
            for middleware in self.request_middleware:
                response = middleware(request)
                if isawaitable(response):
                    response = await response
                if response:
                    return response
        return None

    async def _run_response_middleware(self, request, response):
        if self.response_middleware:
            for middleware in self.response_middleware:
                _response = middleware(request, response)
                if isawaitable(_response):
                    _response = await _response
                if _response:
                    response = _response
                    break
        return response

    def run(self, host='127.0.0.1', port=8000, ssl=None, debug=False,
            sock=None, workers=1, backlog=100, protocol=None):
        self.debug = debug
        self.error_handler.debug = debug
        self.server = Server(self)
        self.server.run(host=host, port=port, ssl=ssl,
                        sock=sock, workers=workers, protocol=protocol)

    def stop(self):
        get_event_loop().stop()

    # -------------------------------------------------------------------- #
    # Request Handling
    # -------------------------------------------------------------------- #

    async def get_body(self, message, channels):
        body = message.get('body', b'')
        if 'body' in channels:
            while True:
                message_chunk = await channels['body'].receive()
                body += message_chunk['content']
                if not message_chunk.get('more_content', False):
                    break
        return body

    async def __call__(self, message, channels):
        try:
            request = None
            channel_name = message.get('channel')
            if (channel_name == 'http.request'
                    or channel_name == 'websocket.connect'):
                # make request
                request = self.request_class(message)
            elif channel_name == 'websocket.receive':
                reply_channel_name = channels['reply'].name
                await self.websocket_channels[reply_channel_name].put(message)
                return
            elif channel_name == 'websocket.disconnect':
                reply_channel_name = channels['reply'].name
                await self.websocket_channels[reply_channel_name].put(message)
                self.websocket_channels.pop(reply_channel_name, None)
                return

            # -------------------------------------------- #
            # Request Middleware
            # -------------------------------------------- #

            request.app = self
            response = await self._run_request_middleware(request)
            # No middleware results
            if not response:
                # -------------------------------------------- #
                # Execute Handler
                # -------------------------------------------- #

                # Fetch handler from router
                handler, args, kwargs, uri = self.router.get(request)
                request.uri_template = uri
                if handler is None:
                    raise ServerError(
                        ('None was returned while requesting a '
                         'handler from the router'))

                # It is request stream
                # FIXME more check
                if self.router.is_stream_handler(request):
                    request.stream = channels['body']
                # websocket
                elif hasattr(handler, 'is_websocket'):
                    request.stream = Queue()
                else:
                    body = await self.get_body(message, channels)
                    message['body'] = body
                    request.body = body
                # Run response handler
                response = handler(request, *args, **kwargs)
                if isawaitable(response):
                    response = await response
            if not hasattr(response, 'get_message'):
                raise ServerError(
                    'response does not have get_message()')
            # websocket
            if isinstance(response, self.websocket_response_class):
                channel_name = channels['reply'].name
                if channel_name not in self.websocket_channels:
                    self.websocket_channels[channel_name] = request.stream
                else:
                    raise ServerError(
                        ('There is a channel_name of websocket.'))
                _message = response.get_message()
                await channels['reply'].send(_message)
                await response.handler(
                    WebSocketReplyChannelProxy(channels['reply'],
                                               self.websocket_channels))
                await channels['reply'].send({
                    'bytes': None,
                    'text': None,
                    'close': True
                })
                return
            # response stream
            if isinstance(response, self.stream_http_response_class):
                _message = response.get_message(True)
                await channels['reply'].send(_message)
                await response.handler(
                    ReplyChannelProxy(channels['reply']))
                await channels['reply'].send({
                    'content': b'',
                    'more_content': False
                })
                return
            _message = response.get_message(False)
        except Exception as e:
            # -------------------------------------------- #
            # Response Generation Failed
            # -------------------------------------------- #

            try:
                response = self.error_handler.response(request, e)
                if isawaitable(response):
                    response = await response
            except Exception as e:
                if self.debug:
                    response = HTTPResponse(
                        'Error while handling error: {}\nStack: {}'.format(
                            e, format_exc()))
                else:
                    response = HTTPResponse(
                        'An error occurred while handling an error')
            _message = response.get_message(False)
        finally:
            # -------------------------------------------- #
            # Response Middleware
            # -------------------------------------------- #
            try:
                # pass chunk
                if 'scheme' not in message:
                    return
                response = await self._run_response_middleware(request,
                                                               response)
                if (not isinstance(response, self.stream_http_response_class)
                    and not isinstance(
                        response, self.websocket_response_class)):
                    _message = response.get_message(False)
            except:
                self.log.exception(
                    'Exception occured in one of response middleware handlers'
                )

        await channels['reply'].send(_message)


class ReplyChannelProxy:

    def __init__(self, reply_channel):
        self._reply_channel = reply_channel

    async def send(self, content):
        message = {
            'content': content,
            'more_content': True
        }
        await self._reply_channel.send(message)


class WebSocketReplyChannelProxy:

    def __init__(self, reply_channel, websocket_channels):
        self._reply_channel = reply_channel
        self._websocket_channels = websocket_channels

    async def send(self, content, close=False):
        if close:
            self._websocket_channels.pop(self._reply_channel.name, None)
        message = {
            'text': content if isinstance(content, str) else None,
            'bytes': content if isinstance(content, bytes) else None,
            'close': close
        }
        await self._reply_channel.send(message)
