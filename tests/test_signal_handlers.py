from mach9 import Mach9
from mach9.response import HTTPResponse
from mach9.testing import HOST, PORT
from unittest.mock import MagicMock
import asyncio
from queue import Queue


async def stop(app, loop):
    await asyncio.sleep(0.1)
    app.stop()

calledq = Queue()


def set_loop(app, loop):
    loop.add_signal_handler = MagicMock()


def after(app, loop):
    calledq.put(loop.add_signal_handler.called)


def test_register_system_signals():
    """Test if mach9 register system signals"""
    app = Mach9('test_register_system_signals')

    @app.route('/hello')
    async def hello_route(request):
        return HTTPResponse()

    app.listener('after_server_start')(stop)
    app.listener('before_server_start')(set_loop)
    app.listener('after_server_stop')(after)

    app.run(HOST, PORT)
    assert calledq.get() is True
