
import unittest

from zope.testing import doctest
from zope.component import provideUtility
from Products.Five import zcml
from zope.component import provideUtility
from zope.interface import classProvides, implements
from collective.transmogrifier.interfaces import ISectionBlueprint, ISection

from Testing import ZopeTestCase as ztc
from Products.PloneTestCase import PloneTestCase as ptc
from Products.PloneTestCase.layer import onsetup
from Products.Five import zcml
from Products.Five import fiveconfigure

from collective.transmogrifier.tests import setUp as baseSetUp
from collective.transmogrifier.tests import tearDown
from collective.transmogrifier.sections.tests import PrettyPrinter
from collective.transmogrifier.sections.tests import SampleSource

from transmogrify.htmlcontentextractor.webcrawler import WebCrawler
from transmogrify.htmlcontentextractor.treeserializer import TreeSerializer
from transmogrify.htmlcontentextractor.typerecognitor import TypeRecognitor
from transmogrify.htmlcontentextractor.safeportaltransforms import  SafePortalTransforms
from transmogrify.htmlcontentextractor.makeattachments import MakeAttachments
from templatefinder import TemplateFinder
from transmogrify.htmlcontentextractor.relinker import Relinker
from transmogrify.htmlcontentextractor.simplexpath import SimpleXPath
from plone.i18n.normalizer import urlnormalizer
from lxml import etree
import lxml.html
import lxml.html.soupparser
from lxml.html.clean import Cleaner
import urlparse
import transmogrify.htmlcontentextractor
from os.path import dirname, abspath
import urllib


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
            item_ = dict(_mimetype="text/html",
                        _site_url="http://test.com/",
                        _path=path,    
                        text=text,
                        _sortorder=order)
            self.items.append(item_)

    def __iter__(self):
        for item in self.previous:
            yield item

        for item in self.items:
            yield item

class HTMLBacklinkSource(HTMLSource):
    classProvides(ISectionBlueprint)
    implements(ISection)

    def __init__(self, transmogrifier, name, options, previous):
        HTMLSource.__init__(self, transmogrifier, name, options, previous)
        pathtoitem = {}
        for item in self.items:
            pathtoitem[item['_site_url']+item['_path']] = item
        for item in self.items:
            parser = lxml.html.soupparser.fromstring(item['text'])
            for element, attribute, rawlink, pos in parser.iterlinks():
                t = urlparse.urlparse(rawlink)
                fragment = t[-1]
                t = t[:-1] + ('',)
                rawlink = urlparse.urlunparse(t)
                base = item['_site_url']+item['_path']
                link = urlparse.urljoin(base, rawlink)
                linked = pathtoitem.get(link)
                if linked:
                    linked.setdefault('_backlinks',[]).append((base,element.text_content()))


class MockPortalTransforms(object):
    def __call__(self, transform, data):
        return 'Transformed %i using the %s transform' % (len(data), transform)
    def convertToData(self, target, data, mimetype=None):
        html='<img src="image01.jpg"><img src="image02.jpg">'
        class dummyfile:
            def __init__(self, text):
                self.text = text
            def __str__(self):
                return self.text+html
            def getSubObjects(self):
                return {'image01.jpg':data,'image02.jpg':data}
        if mimetype is not None:
            return dummyfile( 'Transformed %i from %s to %s' % (
                len(data), mimetype, target) )
        else:
            return dummyfile('Transformed %r to %s' % (data, target) )
    def convertTo(self, target, data, mimetype=None):
        return self.convertToData(target,data,mimetype)



def setUp(test):
    baseSetUp(test)

    from collective.transmogrifier.transmogrifier import Transmogrifier
    test.globs['transmogrifier'] = Transmogrifier(test.globs['plone'])

    import zope.component
    import collective.transmogrifier.sections
    zcml.load_config('meta.zcml', zope.app.component)
    zcml.load_config('configure.zcml', collective.transmogrifier.sections)

    test.globs['plone'].portal_transforms = MockPortalTransforms()

    provideUtility(PrettyPrinter,
        name=u'collective.transmogrifier.sections.tests.pprinter')
    provideUtility(WebCrawler,
        name=u'transmogrify.webcrawler')
    provideUtility(TreeSerializer,
        name=u'transmogrify.htmlcontentextractor')

    provideUtility(HTMLSource,
        name=u'transmogrify.htmlcontentextractor.test.htmlsource')
    provideUtility(HTMLBacklinkSource,
        name=u'transmogrify.htmlcontentextractor.test.htmlbacklinksource')


def SafeATSchemaUpdaterSetUp(test):
    setUp(test)

    from Products.Archetypes.interfaces import IBaseObject
    class MockPortal(object):
        implements(IBaseObject)

        def unrestrictedTraverse(self, path, default):
            return self

        _file_value = None
        _file_filename = None
        _file_mimetype = None
        _file_field = None

        def set(self, name, value, **arguments):
            self._file_field = name
            self._file_value = value
            if 'mimetype' in arguments:
                self._file_mimetype = arguments['mimetype']
            if 'filename' in arguments:
                self._file_filename = arguments['filename']

        def get(self, name):
            return self._file_value

        def checkCreationFlag(self):
            pass

        def unmarkCreationFlag(self):
            pass

        def getField(self, name):
            return self

    test.globs['plone'] = MockPortal()
    test.globs['transmogrifier'].context = test.globs['plone']

    class SafeATSchemaUpdaterSectionSource(SampleSource):
        classProvides(ISectionBlueprint)
        implements(ISection)

        def __init__(self, *args, **kw):
            super(SafeATSchemaUpdaterSectionSource, self).__init__(*args, **kw)
            self.sample = (
                {'_path': '/dummy',
                 'file': 'image content',
                 'file.filename': 'image.jpg',
                 'file.mimetype': 'image/jpeg',},
            )
    provideUtility(SafeATSchemaUpdaterSectionSource,
        name=u'transmogrify.htmlcontentextractor.tests.safeatschemaupdatersource')

def MakeAttachmentsSetUp(test):
    setUp(test)

    class MakeAttachmentsSource(SampleSource):
        classProvides(ISectionBlueprint)
        implements(ISection)

        def __init__(self, *args, **kw):
            super(MakeAttachmentsSource, self).__init__(*args, **kw)
            self.sample = (
                {'_site_url': 'http://www.test.com',
                 '_path': '/item1',},
                {'_site_url': 'http://www.test.com',
                 '_path': '/subitem1',
                 '_backlinks': [('http://www.test.com/subitem2', '')],
                 'title': 'subitem1 title',
                 'decription': 'test if condition is working',
                 '_type': 'Document'},
                {'_site_url': 'http://www.test.com',
                 '_path': '/subitem2',
                 '_backlinks': [('http://www.test.com/subitem1', '')],
                 'title': 'subitem2 title',
                 'image': 'subitem2 image content',
                 '_type': 'Image'},
            )
    provideUtility(MakeAttachmentsSource,
        name=u'transmogrify.htmlcontentextractor.tests.makeattachments')
    provideUtility(MakeAttachments,
        name=u'transmogrify.htmlcontentextractor.makeattachments')

@onsetup
def setup_product():
    """ """
    fiveconfigure.debug_mode = True
    zcml.load_config('configure.zcml', transmogrify.htmlcontentextractor)
    fiveconfigure.debug_mode = False
    ztc.installPackage('plone.app.z3cform')
#    ztc.installPackage('lovely.remotetask')
    ztc.installPackage('transmogrify.htmlcontentextractor')


setup_product()
#ptc.setupPloneSite(extension_profiles=('transmogrify.htmlcontentextractor:default',), with_default_memberarea=False)
ptc.setupPloneSite(products=['transmogrify.htmlcontentextractor'])

class TestCase(ptc.FunctionalTestCase):
    """ We use this base class for all the tests in this package. If necessary,
        we can put common utility or setup code in here. This applies to unit
        test cases. """
    _configure_portal = False

    def beforeTearDown(self):
        pass

    def afterSetUp(self):
        here = abspath(dirname(__file__))
        url = urllib.pathname2url(here)
        self.testsite = 'file://%s/test_staticsite' % url

        self.portal.error_log._ignored_exceptions = ()

        self.portal.acl_users.portal_role_manager.updateRolesList()

        self.portal.acl_users._doAddUser('manager', 'pass', ('Manager',), [])
        self.login('manager')



        from Products.Five.testbrowser import Browser
        self.browser = Browser()
#        self.setRoles(('Manager',))
        self.browser.open(self.portal.absolute_url()+'/login_form')
        self.browser.getControl(name='__ac_name').value = 'manager'
        self.browser.getControl(name='__ac_password').value = 'pass'
        self.browser.getControl(name='submit').click()
        self.browser.open(self.portal.absolute_url())


def test_suite():
    flags = optionflags = doctest.ELLIPSIS | doctest.REPORT_ONLY_FIRST_FAILURE | \
                        doctest.NORMALIZE_WHITESPACE | doctest.REPORT_UDIFF

    return unittest.TestSuite((

        doctest.DocFileSuite('templatefinder.txt', 
                setUp=setUp, 
                optionflags = flags,
                tearDown=tearDown),



    ))

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')


