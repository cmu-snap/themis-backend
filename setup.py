from setuptools import setup

setup(
    name='cctestbed',
    version='0.1',
    py_modules=['cctestbed'],
    install_requires=[
        'Click',
    ],
    entry_points='''
    [console_scripts]
    cctestbed=cctestbed:main
    ''',
)
