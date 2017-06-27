from setuptools import setup


setup_kwargs = {
    'name': 'mach9',
    'author': '38elements',
    'version': '0.0.2',
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
    ]
}

setup(**setup_kwargs)
