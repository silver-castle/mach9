import random

from mach9 import Mach9
from mach9.response import json
from ujson import loads


def test_storage():
    app = Mach9('test_text')

    @app.middleware('request')
    def store(request):
        request['user'] = 'mach9'
        request['sidekick'] = 'tails'
        del request['sidekick']

    @app.route('/')
    def handler(request):
        return json({'user': request.get('user'), 'sidekick': request.get('sidekick')})

    request, response = app.test_client.get('/')

    response_json = loads(response.text)
    assert response_json['user'] == 'mach9'
    assert response_json.get('sidekick') is None


def test_app_injection():
    app = Mach9('test_app_injection')
    expected = random.choice(range(0, 100))

    @app.listener('after_server_start')
    async def inject_data(app, loop):
        app.injected = expected

    @app.get('/')
    async def handler(request):
        return json({'injected': request.app.injected})

    request, response = app.test_client.get('/')

    response_json = loads(response.text)
    assert response_json['injected'] == expected
