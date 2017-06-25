import logging
import logging.config
import re
from asyncio import get_event_loop
from collections import deque, defaultdict
from functools import partial
from inspect import isawaitable, stack, getmodulename
from traceback import format_exc
from urllib.parse import urlencode, urlunparse
from ssl import create_default_context, Purpose

from mach9.config import Config, LOGGING
from mach9.exceptions import ServerError, URLBuildError, Mach9Exception
from mach9.handlers import ErrorHandler
from mach9.log import log as _log
from mach9.log import log as _netlog
from mach9.response import HTTPResponse
from mach9.router import Router
from mach9.signal import Signal
from mach9.server import serve as _serve
from mach9.server import serve_multiple as _serve_multiple
from mach9.http import HttpProtocol, BodyChannel, ReplyChannel
from mach9.request import Request
from mach9.static import register as static_register
from mach9.testing import Mach9TestClient
from mach9.views import CompositionView
from mach9.timer import update_current_time as _update_current_time
from mach9.timer import get_current_time as _get_current_time


class Mach9:

    def __init__(self, name=None, router=None, error_handler=None,
                 load_env=True, request_class=None, protocol=None,
                 serve=None, serve_multiple=None, log=None, netlog=None,
                 log_config=LOGGING, update_current_time=None,
                 get_current_time=None, composition_view=None,
                 body_channel_class=None, reply_channel_class=None):

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

        self.name = name
        self.router = router or Router(_composition_view)
        self.request_class = request_class or Request
        self.error_handler = error_handler or ErrorHandler(self.log)
        self.config = Config(load_env=load_env)
        self.log_config = log_config
        self.request_middleware = deque()
        self.response_middleware = deque()
        self.blueprints = {}
        self._blueprint_order = []
        self.protocol = protocol or HttpProtocol
        self.body_channel_class = body_channel_class or BodyChannel
        self.reply_channel_class = reply_channel_class or ReplyChannel
        self.debug = None
        self.sock = None
        self.listeners = defaultdict(list)
        self.is_running = False
        self.is_request_stream = False
        self.serve = serve or _serve
        self.serve_multiple = serve_multiple or _serve_multiple
        self.netlog = netlog or _netlog
        self.update_current_time = update_current_time or _update_current_time
        self.get_current_time = get_current_time or _get_current_time

    @property
    def loop(self):
        '''Synonymous with asyncio.get_event_loop().

        Only supported when using the `app.run` method.
        '''
        if not self.is_running:
            raise Mach9Exception(
                'Loop can only be retrieved after the app has started '
                'running. Not supported with `create_server` function')
        return get_event_loop()

    # -------------------------------------------------------------------- #
    # Registration
    # -------------------------------------------------------------------- #

    def add_task(self, task):
        '''Schedule a task to run later, after the loop has started.
        Different from asyncio.ensure_future in that it does not
        also return a future, and the actual ensure_future call
        is delayed until before server start.

        :param task: future, couroutine or awaitable
        '''
        @self.listener('before_server_start')
        def run(app, loop):
            if callable(task):
                loop.create_task(task())
            else:
                loop.create_task(task)

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
              strict_slashes=False, stream=False):
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

        if stream:
            self.is_request_stream = True

        def response(handler):
            if stream:
                handler.is_stream = stream
            self.router.add(uri=uri, methods=methods, handler=handler,
                            host=host, strict_slashes=strict_slashes)
            return handler

        return response

    # Shorthand method decorators
    def get(self, uri, host=None, strict_slashes=False):
        return self.route(uri, methods=frozenset({'GET'}), host=host,
                          strict_slashes=strict_slashes)

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
        if isinstance(handler, CompositionView):
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

    def run(self, host='127.0.0.1', port=8000, debug=False, ssl=None,
            sock=None, workers=1, backlog=100, register_sys_signals=True):
        '''Run the HTTP Server and listen until keyboard interrupt or term
        signal. On termination, drain connections before closing.

        :param host: Address to host on
        :param port: Port to host on
        :param debug: Enables debug output (slows server)
        :param ssl: SSLContext, or location of certificate and key
                            for SSL encryption of worker(s)
        :param sock: Socket for the server to accept connections from
        :param workers: Number of processes
                            received before it is respected
        :param backlog:
        :param register_sys_signals:
        :return: Nothing
        '''
        server_settings = self._helper(
            host=host, port=port, debug=debug, ssl=ssl, sock=sock,
            workers=workers, backlog=backlog,
            register_sys_signals=register_sys_signals,
            has_log=self.log_config is not None)

        try:
            self.is_running = True
            if workers == 1:
                self.serve(**server_settings)
            else:
                self.serve_multiple(server_settings, workers)
        except:
            self.log.exception(
                'Experienced exception while trying to serve')
            raise
        finally:
            self.is_running = False
        self.log.info('Server Stopped')

    def stop(self):
        '''This kills the Mach9'''
        get_event_loop().stop()

    def __call__(self):
        '''gunicorn compatibility'''
        return self

    async def create_server(self, host='127.0.0.1', port=8000, debug=False,
                            ssl=None, sock=None, backlog=100):
        '''Asynchronous version of `run`.

        NOTE: This does not support multiprocessing and is not the preferred
              way to run a Mach9 application.
        '''
        server_settings = self._helper(
            host=host, port=port, debug=debug, ssl=ssl, sock=sock,
            loop=get_event_loop(), backlog=backlog, run_async=True,
            has_log=self.log_config is not None)

        return await self.serve(**server_settings)

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

    def _helper(self, host='127.0.0.1', port=8000, debug=False,
                ssl=None, sock=None, workers=1, loop=None,
                backlog=100, register_sys_signals=True,
                run_async=False, has_log=True):
        '''Helper function used by `run` and `create_server`.'''

        if isinstance(ssl, dict):
            # try common aliaseses
            cert = ssl.get('cert') or ssl.get('certificate')
            key = ssl.get('key') or ssl.get('keyfile')
            if cert is None or key is None:
                raise ValueError('SSLContext or certificate and key required.')
            context = create_default_context(purpose=Purpose.CLIENT_AUTH)
            context.load_cert_chain(cert, keyfile=key)
            ssl = context

        self.error_handler.debug = debug
        self.debug = debug

        server_settings = {
            'protocol': self.protocol,
            'request_handler': self.asgi_handler,
            'error_handler': self.error_handler,
            'log': self.log,
            'netlog': self.netlog,
            'update_current_time': self.update_current_time,
            'get_current_time': self.get_current_time,
            'host': host,
            'port': port,
            'sock': sock,
            'ssl': ssl,
            'signal': Signal(),
            'debug': debug,
            'request_timeout': self.config.REQUEST_TIMEOUT,
            'request_max_size': self.config.REQUEST_MAX_SIZE,
            'keep_alive': self.config.KEEP_ALIVE,
            'loop': loop,
            'register_sys_signals': register_sys_signals,
            'request_class': self.request_class,
            'body_channel_class': self.body_channel_class,
            'reply_channel_class': self.reply_channel_class,
            'backlog': backlog,
            'has_log': has_log
        }

        # -------------------------------------------- #
        # Register start/stop events
        # -------------------------------------------- #

        for event_name, settings_name, reverse in (
                ('before_server_start', 'before_start', False),
                ('after_server_start', 'after_start', False),
                ('before_server_stop', 'before_stop', True),
                ('after_server_stop', 'after_stop', True),
        ):
            listeners = self.listeners[event_name].copy()
            if reverse:
                listeners.reverse()
            # Prepend mach9 to the arguments when listeners are triggered
            listeners = [partial(listener, self) for listener in listeners]
            server_settings[settings_name] = listeners

        if debug:
            self.log.setLevel(logging.DEBUG)

        if run_async:
            server_settings['run_async'] = True

        # Serve
        if host and port:
            proto = 'http'
            if ssl is not None:
                proto = 'https'
            self.log.info('Goin\' Fast @ {}://{}:{}'.format(proto, host, port))
        return server_settings

    async def get_body(self, message, channels):
        body = message.get('body', b'')
        if 'body' in channels:
            while True:
                message_chunk = await channels['body'].receive()
                body += message_chunk['content']
                if not message_chunk.get('more_content', False):
                    break
        return body

    # -------------------------------------------------------------------- #
    # Request Handling
    # -------------------------------------------------------------------- #
    async def asgi_handler(self, message, channels):
        try:
            # make request
            request = self.request_class(message)

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

                # It is not request stream
                if self.router.is_stream_handler(request):
                    request.stream = channels['body']
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
                response = await self._run_response_middleware(request,
                                                               response)
                _message = response.get_message(False)
            except:
                self.log.exception(
                    'Exception occured in one of response middleware handlers'
                )

        await channels['reply'].send(_message)
