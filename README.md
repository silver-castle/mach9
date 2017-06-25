# Mach9

Mach9 is a web application framework based [ASGI](http://channels.readthedocs.io/en/stable/asgi.html) and `async/await`.  

## Features

### ASGI

Mach9 is based [ASGI](http://channels.readthedocs.io/en/stable/asgi.html).  
You can integrate Mach9 and [Uvicorn](https://github.com/encode/uvicorn).

Details are [here](https://github.com/silver-castle/mach9-cookbook/blob/master/uvicorn.md).

### Restructrurable

Mach9 is restructrurable framework.  
Most Mach9's components are independent.  
You can replace Mach9's components.  
You can use Mach9's components to making your framework.  
Mach9 has following components.  

* Blueprints
* Config
* Request
* Response
* Channel
* Protocol
* Router
* Server
* Signal
* Timer
* ErrorHandler
* View
* Exceptions
* Log

Details are [here](https://github.com/silver-castle/mach9-cookbook/blob/master/restructure.md).

### Asynchronous

Mach9 is based async/await syntax from Python 3.5.

### Small and Simple

Mach9 thinks that small and simple is important.

## Installation

```
pip install mach9
```

## Usage

```python
from mach9 import Mach9
from mach9.response import text

app = Mach9(log_config=None)


@app.route('/')
async def test(request):
    return text('Hello world!')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=False)
```

## Support

* Linux
* Mac OS X
* Python3.6+

## Goal

Mach9 is an experimental project for finding best practice of python asynchronous web framework.  
This is prototype, not product.  

## License

Mach9 is MIT License.  
Mach9 is a fork of Sanic.  
Sanic is MIT License.  
See LICENSE.
