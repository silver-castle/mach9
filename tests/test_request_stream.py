from mach9 import Mach9
from mach9.http import BodyChannel
from mach9.blueprints import Blueprint
from mach9.views import CompositionView
from mach9.views import HTTPMethodView
from mach9.views import stream as stream_decorator
from mach9.response import text

data = 'abc' * 100000


def test_request_stream_method_view():
    '''for self.is_request_stream = True'''

    app = Mach9('test_request_stream_method_view')

    class SimpleView(HTTPMethodView):

        def get(self, request):
            assert request.stream is None
            return text('OK')

        @stream_decorator
        async def post(self, request):
            assert isinstance(request.stream, BodyChannel)
            result = ''
            while True:
                body_chunk = await request.stream.receive()
                if body_chunk['more_content'] is False:
                    break
                result += body_chunk['content'].decode('utf-8')
            return text(result)

    app.add_route(SimpleView.as_view(), '/method_view')

    assert app.is_request_stream is True

    request, response = app.test_client.get('/method_view')
    assert response.status == 200
    assert response.text == 'OK'

    request, response = app.test_client.post('/method_view', data=data)
    assert response.status == 200
    assert response.text == data


def test_request_stream_app():
    '''for self.is_request_stream = True and decorators'''

    app = Mach9('test_request_stream_app')

    @app.get('/get')
    async def get(request):
        assert request.stream is None
        return text('GET')

    @app.head('/head')
    async def head(request):
        assert request.stream is None
        return text('HEAD')

    @app.delete('/delete')
    async def delete(request):
        assert request.stream is None
        return text('DELETE')

    @app.options('/options')
    async def options(request):
        assert request.stream is None
        return text('OPTIONS')

    @app.post('/_post/<id>')
    async def _post(request, id):
        assert request.stream is None
        return text('_POST')

    @app.post('/post/<id>', stream=True)
    async def post(request, id):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    @app.put('/_put')
    async def _put(request):
        assert request.stream is None
        return text('_PUT')

    @app.put('/put', stream=True)
    async def put(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    @app.patch('/_patch')
    async def _patch(request):
        assert request.stream is None
        return text('_PATCH')

    @app.patch('/patch', stream=True)
    async def patch(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    assert app.is_request_stream is True

    request, response = app.test_client.post('/not_found')
    assert response.status == 404

    request, response = app.test_client.get('/get')
    assert response.status == 200
    assert response.text == 'GET'

    request, response = app.test_client.head('/head')
    assert response.status == 200
    assert response.text == ''

    request, response = app.test_client.delete('/delete')
    assert response.status == 200
    assert response.text == 'DELETE'

    request, response = app.test_client.options('/options')
    assert response.status == 200
    assert response.text == 'OPTIONS'

    request, response = app.test_client.post('/_post/1', data=data)
    assert response.status == 200
    assert response.text == '_POST'

    request, response = app.test_client.post('/post/1', data=data)
    assert response.status == 200
    assert response.text == data

    request, response = app.test_client.put('/_put', data=data)
    assert response.status == 200
    assert response.text == '_PUT'

    request, response = app.test_client.put('/put', data=data)
    assert response.status == 200
    assert response.text == data

    request, response = app.test_client.patch('/_patch', data=data)
    assert response.status == 200
    assert response.text == '_PATCH'

    request, response = app.test_client.patch('/patch', data=data)
    assert response.status == 200
    assert response.text == data


def test_request_stream_blueprint():
    '''for self.is_request_stream = True'''

    app = Mach9('test_request_stream_blueprint')
    bp = Blueprint('test_blueprint_request_stream_blueprint')

    @app.get('/get')
    async def get(request):
        assert request.stream is None
        return text('GET')

    @bp.head('/head')
    async def head(request):
        assert request.stream is None
        return text('HEAD')

    @bp.delete('/delete')
    async def delete(request):
        assert request.stream is None
        return text('DELETE')

    @bp.options('/options')
    async def options(request):
        assert request.stream is None
        return text('OPTIONS')

    @bp.post('/_post/<id>')
    async def _post(request, id):
        assert request.stream is None
        return text('_POST')

    @bp.post('/post/<id>', stream=True)
    async def post(request, id):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    @bp.put('/_put')
    async def _put(request):
        assert request.stream is None
        return text('_PUT')

    @bp.put('/put', stream=True)
    async def put(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    @bp.patch('/_patch')
    async def _patch(request):
        assert request.stream is None
        return text('_PATCH')

    @bp.patch('/patch', stream=True)
    async def patch(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    app.blueprint(bp)

    assert app.is_request_stream is True

    request, response = app.test_client.get('/get')
    assert response.status == 200
    assert response.text == 'GET'

    request, response = app.test_client.head('/head')
    assert response.status == 200
    assert response.text == ''

    request, response = app.test_client.delete('/delete')
    assert response.status == 200
    assert response.text == 'DELETE'

    request, response = app.test_client.options('/options')
    assert response.status == 200
    assert response.text == 'OPTIONS'

    request, response = app.test_client.post('/_post/1', data=data)
    assert response.status == 200
    assert response.text == '_POST'

    request, response = app.test_client.post('/post/1', data=data)
    assert response.status == 200
    assert response.text == data

    request, response = app.test_client.put('/_put', data=data)
    assert response.status == 200
    assert response.text == '_PUT'

    request, response = app.test_client.put('/put', data=data)
    assert response.status == 200
    assert response.text == data

    request, response = app.test_client.patch('/_patch', data=data)
    assert response.status == 200
    assert response.text == '_PATCH'

    request, response = app.test_client.patch('/patch', data=data)
    assert response.status == 200
    assert response.text == data


def test_request_stream_composition_view():
    '''for self.is_request_stream = True'''

    app = Mach9('test_request_stream__composition_view')

    def get_handler(request):
        assert request.stream is None
        return text('OK')

    async def post_handler(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    view = CompositionView()
    view.add(['GET'], get_handler)
    view.add(['POST'], post_handler, stream=True)
    app.add_route(view, '/composition_view')

    assert app.is_request_stream is True

    request, response = app.test_client.get('/composition_view')
    assert response.status == 200
    assert response.text == 'OK'

    request, response = app.test_client.post('/composition_view', data=data)
    assert response.status == 200
    assert response.text == data


def test_request_stream():
    '''test for complex application'''

    bp = Blueprint('test_blueprint_request_stream')
    app = Mach9('test_request_stream')

    class SimpleView(HTTPMethodView):

        def get(self, request):
            assert request.stream is None
            return text('OK')

        @stream_decorator
        async def post(self, request):
            assert isinstance(request.stream, BodyChannel)
            result = ''
            while True:
                body_chunk = await request.stream.receive()
                if body_chunk['more_content'] is False:
                    break
                result += body_chunk['content'].decode('utf-8')
            return text(result)

    @app.post('/stream', stream=True)
    async def handler(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    @app.get('/get')
    async def get(request):
        assert request.stream is None
        return text('OK')

    @bp.post('/bp_stream', stream=True)
    async def bp_stream(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    @bp.get('/bp_get')
    async def bp_get(request):
        assert request.stream is None
        return text('OK')

    def get_handler(request):
        assert request.stream is None
        return text('OK')

    async def post_handler(request):
        assert isinstance(request.stream, BodyChannel)
        result = ''
        while True:
            body_chunk = await request.stream.receive()
            if body_chunk['more_content'] is False:
                break
            result += body_chunk['content'].decode('utf-8')
        return text(result)

    app.add_route(SimpleView.as_view(), '/method_view')

    view = CompositionView()
    view.add(['GET'], get_handler)
    view.add(['POST'], post_handler, stream=True)

    app.blueprint(bp)

    app.add_route(view, '/composition_view')

    assert app.is_request_stream is True

    request, response = app.test_client.get('/method_view')
    assert response.status == 200
    assert response.text == 'OK'

    request, response = app.test_client.post('/method_view', data=data)
    assert response.status == 200
    assert response.text == data

    request, response = app.test_client.get('/composition_view')
    assert response.status == 200
    assert response.text == 'OK'

    request, response = app.test_client.post('/composition_view', data=data)
    assert response.status == 200
    assert response.text == data

    request, response = app.test_client.get('/get')
    assert response.status == 200
    assert response.text == 'OK'

    request, response = app.test_client.post('/stream', data=data)
    assert response.status == 200
    assert response.text == data

    request, response = app.test_client.get('/bp_get')
    assert response.status == 200
    assert response.text == 'OK'

    request, response = app.test_client.post('/bp_stream', data=data)
    assert response.status == 200
    assert response.text == data
