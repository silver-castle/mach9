from setuptools import setup


setup_kwargs = {
    'name': 'mach9',
    'author': '38elements',
    'url': 'https://github.com/silver-castle/mach9',
    'description': 'a web application framework based ASGI and async/await.',
    'version': '0.0.4',
    'license': 'MIT License',
    'packages': ['mach9'],
    'classifiers': [
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Web Environment',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
    ],
    'install_requires': [
        'httptools',
        'uvloop',
        'ujson',
        'aiofiles',
        'websockets',
    ]
}

setup(**setup_kwargs)
