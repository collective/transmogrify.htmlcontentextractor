
import unittest
import sys
import  zope.app.component

#from zope.testing import doctest
import doctest
from zope.component import provideUtility
from Products.Five import zcml
from zope.interface import classProvides, implements
from collective.transmogrifier.interfaces import ISectionBlueprint, ISection

from Testing import ZopeTestCase as ztc
from Products.Five import fiveconfigure

from collective.transmogrifier.tests import setUp as baseSetUp
from collective.transmogrifier.tests import tearDown
from collective.transmogrifier.sections.tests import PrettyPrinter
from transmogrify.htmlcontentextractor.templatefinder import TemplateFinder
import transmogrify.htmlcontentextractor
import logging

globs = dict(
#    testtransmogrifier=runner.testtransmogrifier,
    )


class HTMLSource(object):
    classProvides(ISectionBlueprint)
    implements(ISection)

    def __init__(self, transmogrifier, name, options, previous):
        self.previous = previous
        self.items = []
        for order,item in zip(range(0,len(options)),options.items()):
            path,text = item 
            if path in ['blueprint']:
                continue
            item_ = dict(
#                _mimetype="text/html",
#                 _site_url="http://test.com/",
                 _path=path,
                 text=text,
#                        _sortorder=order,
                 )
            self.items.append(item_)

    def __iter__(self):
        for item in self.previous:
            yield item

        for item in self.items:
            yield item


def setUp(test):
    baseSetUp(test)

    from collective.transmogrifier.transmogrifier import Transmogrifier
    from collective.transmogrifier.tests import registerConfig
    test.globs['transmogrifier'] = Transmogrifier(test.globs['plone'])
    test.globs['registerConfig'] = registerConfig
    test.globs.update(globs)

    import zope.component
    import collective.transmogrifier.sections
    zcml.load_config('meta.zcml', zope.app.component)
    zcml.load_config('configure.zcml', collective.transmogrifier.sections)
    zcml.load_config('configure.zcml', collective.transmogrifier.sections.tests)
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)



    provideUtility(PrettyPrinter,
        name=u'collective.transmogrifier.sections.tests.pprinter')
    provideUtility(TemplateFinder,
        name=u'transmogrify.htmlcontentextractor')
    provideUtility(HTMLSource,
        name=u'transmogrify.htmlcontentextractor.test.htmlsource')


#@onsetup
def setup_product():
    """ """
    fiveconfigure.debug_mode = True
    zcml.load_config('configure.zcml', transmogrify.htmlcontentextractor)
    fiveconfigure.debug_mode = False
    ztc.installPackage('plone.app.z3cform')
#    ztc.installPackage('lovely.remotetask')
    ztc.installPackage('transmogrify.htmlcontentextractor')


#setup_product()
#ptc.setupPloneSite(extension_profiles=('transmogrify.htmlcontentextractor:default',), with_default_memberarea=False)
#ptc.setupPloneSite(products=['transmogrify.htmlcontentextractor'])

flags = optionflags = doctest.ELLIPSIS | doctest.REPORT_ONLY_FIRST_FAILURE | \
                        doctest.NORMALIZE_WHITESPACE | doctest.REPORT_UDIFF

#def test_suite():
#    #suite = unittest.findTestCases(sys.modules[__name__])
#    suite = unittest.TestSuite()
#    suite.addTests((
#        doctest.DocFileSuite('../templatefinder.txt',
#                setUp=setUp,
#                optionflags = flags,
#                tearDown=tearDown),
#
#
#
#    ))
#    return suite
def test_suite():
    suite = unittest.TestSuite((
            doctest.DocFileSuite(
                '../templatefinder.txt',
                setUp=setUp,
                tearDown=tearDown,
                optionflags=optionflags,
                ),
            ))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')


