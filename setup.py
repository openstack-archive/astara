from setuptools import setup, find_packages

packages = [p for p in find_packages()
            if not p.startswith('test')]

setup(
    name='Akanda Router Update Generator',
    version='0.1.5',
    description='A service that manages tenant Akanda router instances',
    author='DreamHost',
    author_email='dev-community@dreamhost.com',
    url='http://github.com/dreamhost/akanda-rug',
    license='BSD',
    install_requires=[
        'netaddr>=0.7.5',
        'httplib2>=0.7.2',
        'python-quantumclient>=2.1'
    ],
    namespace_packages=['akanda'],
    packages=packages,
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'akanda-rug-service=akanda.rug.service:main'
        ]
    },
)
