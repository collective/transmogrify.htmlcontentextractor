from setuptools import setup, find_packages
import os
import re

version = '1.1'


def docstring(file):
    py = open(os.path.join("transmogrify", "htmlcontentextractor", file)).read()
    return re.findall('"""(.*?)"""', py, re.DOTALL)[0]

install_requires=[
    'setuptools',
    # -*- Extra requirements: -*-
    'lxml',
    'BeautifulSoup',
    'collective.transmogrifier',
    'zope.app.pagetemplate',
    'zope.app.component',
    ]
try:
    from collections import OrderedDict
except ImportError:
    # No OrderedDict, add `ordereddict` to requirements
    install_requires.append('ordereddict')

setup(name='transmogrify.htmlcontentextractor',
      version=version,
      description="This blueprint extracts out title, description and body from html "
                "either via xpath or by automatic cluster analysis",
      long_description=open('README.rst').read() + '\n'+
                        docstring('templatefinder.py') + \
                        docstring('autofinder.py') + \
                        "Detailed tests\n================\n" + \
                       open(os.path.join("transmogrify", "htmlcontentextractor", "templatefinder.txt")).read() + "\n" +
                       open(os.path.join("docs", "HISTORY.txt")).read(),
      # Get more strings from http://www.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
        ],
      keywords='transmogrifier blueprint funnelweb source plone import conversion microsoft office',
      author='Dylan Jay',
      author_email='software@pretaweb.com',
      url='http://github.com/djay/transmogrify.htmlcontentextractor',
      license='GPL',
      packages=find_packages(exclude=['ez_setup']),
      namespace_packages=['transmogrify'],
      include_package_data=True,
      zip_safe=False,
      install_requires=install_requires,
      entry_points="""
            [z3c.autoinclude.plugin]
            target = transmogrify
            """,
            )
