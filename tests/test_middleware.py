from json import loads as json_loads, dumps as json_dumps
from mach9 import Mach9
from mach9.request import Request
from mach9.response import json, text, HTTPResponse
from mach9.exceptions import NotFound


# ------------------------------------------------------------ #
#  GET
# ------------------------------------------------------------ #

def test_middleware_request():
    app = Mach9('test_middleware_request')

    results = []

    @app.middleware
    async def handler(request):
        results.append(request)

    @app.route('/')
    async def handler(request):
        return text('OK')

    request, response = app.test_client.get('/')

    assert response.text == 'OK'
    assert type(results[0]) is Request


def test_middleware_response():
    app = Mach9('test_middleware_response')

    results = []

    @app.middleware('request')
    async def process_response(request):
        results.append(request)

    @app.middleware('response')
    async def process_response(request, response):
        results.append(request)
        results.append(response)

    @app.route('/')
    async def handler(request):
        return text('OK')

    request, response = app.test_client.get('/')

    assert response.text == 'OK'
    assert type(results[0]) is Request
    assert type(results[1]) is Request
    assert isinstance(results[2], HTTPResponse)


def test_middleware_response_exception():
    app = Mach9('test_middleware_response_exception')
    result = {'status_code': None}

    @app.middleware('response')
    async def process_response(reqest, response):
        result['status_code'] = response.status
        return response

    @app.exception(NotFound)
    async def error_handler(request, exception):
        return text('OK', exception.status_code)

    @app.route('/')
    async def handler(request):
        return text('FAIL')

    request, response = app.test_client.get('/page_not_found')
    assert response.text == 'OK'
    assert result['status_code'] == 404

def test_middleware_override_request():
    app = Mach9('test_middleware_override_request')

    @app.middleware
    async def halt_request(request):
        return text('OK')

    @app.route('/')
    async def handler(request):
        return text('FAIL')

    response = app.test_client.get('/', gather_request=False)

    assert response.status == 200
    assert response.text == 'OK'


def test_middleware_override_response():
    app = Mach9('test_middleware_override_response')

    @app.middleware('response')
    async def process_response(request, response):
        return text('OK')

    @app.route('/')
    async def handler(request):
        return text('FAIL')

    request, response = app.test_client.get('/')

    assert response.status == 200
    assert response.text == 'OK'



def test_middleware_order():
    app = Mach9('test_middleware_order')

    order = []

    @app.middleware('request')
    async def request1(request):
        order.append(1)

    @app.middleware('request')
    async def request2(request):
        order.append(2)

    @app.middleware('request')
    async def request3(request):
        order.append(3)

    @app.middleware('response')
    async def response1(request, response):
        order.append(6)

    @app.middleware('response')
    async def response2(request, response):
        order.append(5)

    @app.middleware('response')
    async def response3(request, response):
        order.append(4)

    @app.route('/')
    async def handler(request):
        return text('OK')

    request, response = app.test_client.get('/')

    assert response.status == 200
    assert order == [1,2,3,4,5,6]
