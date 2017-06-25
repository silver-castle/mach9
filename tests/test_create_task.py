from mach9 import Mach9
from mach9.response import text
from threading import Event
import asyncio


def test_create_task():
    e = Event()

    async def coro():
        await asyncio.sleep(0.05)
        e.set()

    app = Mach9('test_create_task')
    app.add_task(coro)

    @app.route('/early')
    def not_set(request):
        return text(e.is_set())

    @app.route('/late')
    async def set(request):
        await asyncio.sleep(0.1)
        return text(e.is_set())

    request, response = app.test_client.get('/early')
    assert response.body == b'False'

    request, response = app.test_client.get('/late')
    assert response.body == b'True'
