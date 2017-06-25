import pytest
from random import choice
import inspect
import os
from aiofiles import os as async_os
from mimetypes import guess_type
from urllib.parse import unquote

from mach9 import Mach9
from mach9.response import HTTPResponse, file


def test_response_body_not_a_string():
    """Test when a response body sent from the application is not a string"""
    app = Mach9('response_body_not_a_string')
    random_num = choice(range(1000))

    @app.route('/hello')
    async def hello_route(request):
        return HTTPResponse(body=random_num)

    request, response = app.test_client.get('/hello')
    assert response.text == str(random_num)


@pytest.fixture
def static_file_directory():
    """The static directory to serve"""
    current_file = inspect.getfile(inspect.currentframe())
    current_directory = os.path.dirname(os.path.abspath(current_file))
    static_directory = os.path.join(current_directory, 'static')
    return static_directory


def get_file_content(static_file_directory, file_name):
    """The content of the static file to check"""
    with open(os.path.join(static_file_directory, file_name), 'rb') as file:
        return file.read()


@pytest.mark.parametrize(
    'file_name', ['test.file', 'decode me.txt', 'python.png'])
def test_file_response(file_name, static_file_directory):
    app = Mach9('test_file_helper')

    @app.route('/files/<filename>', methods=['GET'])
    def file_route(request, filename):
        file_path = os.path.join(static_file_directory, filename)
        file_path = os.path.abspath(unquote(file_path))
        return file(
            file_path, mime_type=guess_type(file_path)[0] or 'text/plain')

    request, response = app.test_client.get('/files/{}'.format(file_name))
    assert response.status == 200
    assert response.body == get_file_content(static_file_directory, file_name)


@pytest.mark.parametrize('file_name', ['test.file', 'decode me.txt'])
def test_file_head_response(file_name, static_file_directory):
    app = Mach9('test_file_helper')

    @app.route('/files/<filename>', methods=['GET', 'HEAD'])
    async def file_route(request, filename):
        file_path = os.path.join(static_file_directory, filename)
        file_path = os.path.abspath(unquote(file_path))
        stats = await async_os.stat(file_path)
        headers = dict()
        headers['Accept-Ranges'] = 'bytes'
        headers['Content-Length'] = str(stats.st_size)
        if request.method == "HEAD":
            return HTTPResponse(
                headers=headers,
                content_type=guess_type(file_path)[0] or 'text/plain')
        else:
            return file(file_path, headers=headers,
                        mime_type=guess_type(file_path)[0] or 'text/plain')

    request, response = app.test_client.head('/files/{}'.format(file_name))
    assert response.status == 200
    assert 'Accept-Ranges' in response.headers
    assert 'Content-Length' in response.headers
    assert int(response.headers[
               'Content-Length']) == len(
                   get_file_content(static_file_directory, file_name))
