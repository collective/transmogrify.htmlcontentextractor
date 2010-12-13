
import fnmatch
from zope.interface import classProvides
from zope.interface import implements
from collective.transmogrifier.interfaces import ISectionBlueprint
from collective.transmogrifier.interfaces import ISection
from collective.transmogrifier.utils import Matcher
from collective.transmogrifier.utils import Condition


from webstemmer.analyze import PageFeeder, LayoutAnalyzer, LayoutCluster
from webstemmer.extract import TextExtractor, LayoutPatternSet, LayoutPattern
from webstemmer.layoutils import sigchars, get_textblocks, retrieve_blocks, WEBSTEMMER_VERSION, KEY_ATTRS
from webstemmer.zipdb import ACLDB
from webstemmer.htmldom import parse
from lxml import etree
import lxml.html
import lxml.html.soupparser

from StringIO import StringIO
from sys import stderr

import logging


#patch LayoutCluster to make it LayoutPattern
def match_blocks(self, blocks0, strict=True):
    diffs = [ d for (d,m,p) in self.pattern ]
    mains = [ m for (d,m,p) in self.pattern ]
    paths = [ p for (d,m,p) in self.pattern ]
    layout = []
    for (diffscore,mainscore,blocks1,path) in zip(diffs, mains, retrieve_blocks(paths, blocks0), paths):
      if strict and not blocks1:
        return None
      layout.append(LayoutSection(len(layout), diffscore, mainscore, blocks1, path))
    return layout
LayoutCluster.match_blocks = match_blocks
LayoutCluster.main_sectno = -1

class LayoutSection:

  def __init__(self, id, diffscore, mainscore, blocks,path):
    self.id = id
    self.diffscore = diffscore
    self.mainscore = mainscore
    self.weight = sum( b.weight for b in blocks )
    self.blocks = blocks
    self.path = path
    return




"""
XPath Tests
===========

We want to take webstemmers patterns and get the actually html rather than just
the text. To do this we will convert a pattern to xpath

    >>> pat = 'div:class=section1/p:align=center:class=msonormal/span'
    >>> xp = toXPath(pat)
    '//div[re:test(@class,"^section1$","i")]/p[re:test(@align,"^center$","i")][re:test(@class,"^msonormal$","i")]/span'

Lets check it gets the right parts of the text

    >>> text = '<div class="Section1">\n\n<p class="MsoNormal" align="center" style="text-align:center"><b style="mso-bidi-font-weight:
 normal"><span lang="EN-AU" style="font-size:20.0pt"/></b></p>\n\n<p class="MsoNormal" align="center" style="text-align:
center"><b style="mso-bidi-font-weight: normal"><span lang="EN-AU" style="font-size:20.0pt">Customer Service Standards</
span></b></p>\n\n<p class="MsoNormal"><span lang="EN-AU"/></p>\n\n<p class="MsoNormal"><span lang="EN-AU"/></p>\n\n<p cl
ass="MsoNormal"><span lang="EN-AU"/></p>\n\n<p class="MsoNormal" style="margin-top:0cm;margin-right:-23.55pt;margin-bott
om: 0cm;margin-left:45.1pt;margin-bottom:.0001pt;text-indent:-27.0pt;mso-pagination: none;mso-list:l2 level1 lfo3;tab-st
ops:list 45.0pt"><b style="mso-bidi-font-weight:normal"><span lang="EN-AU" style="font-size:16.0pt; mso-fareast-font-fam
ily:Arial"><span style="mso-list:Ignore">1.<span style="font:7.0pt "/>Times New Roman""&gt;\n</span></span></b></p><b st
yle="mso-bidi-font-weight:normal"><span lang="EN-AU" style="font-size:16.0pt">Care for the customer and show respect for
\nthem and their property.</span></b></div>'

    >>> parser = etree.XMLParser(recover=True)
    >>> tree = etree.parse(StringIO(text), parser)
    >>> nodes = tree.xpath(xp,namespaces=ns)
    >>> result = etree.tostring(nodes[0])


"""


ns = {'re':"http://exslt.org/regular-expressions"}

import re
attr = re.compile(r':(?P<attr>[^/:]*)=(?P<val>[^/:\*\.\?]*)')
reattr = re.compile(r':(?P<attr>[^/:]*)=(?P<val>[^/:]*)')
def toXPath(pat):
    #td:valign=top/p:class=msonormal/span
    #TODO we need to make simpler xpath when re isn't being used
    pat = attr.sub(r'[@\g<attr> = "\g<val>"]', pat)
    pat = reattr.sub(r'[re:test(@\g<attr>,"^\g<val>$","i")]', pat)
    pat = pat.replace('/', '//')
    return "//" + pat


default_charset='utf-8'

class AutoFinder(object):
    classProvides(ISectionBlueprint)
    implements(ISection)




    def __init__(self, transmogrifier, name, options, previous):
        self.previous = previous
        self.disable = options.get('disable','False')
        self.disable = self.disable.lower() == 'true'
        self.condition = Condition(options.get('condition', 'python:True'),
                                   transmogrifier, name, options)
        self.log = logging.getLogger(name)


    def __iter__(self):
        previous = self.previous
        (debug, cluster_threshold, title_threshold, score_threshold) = (0, 0.97, 0.6, 100)
        mangle_pat = None
        linkinfo = 'linkinfo'
        #
        analyzer = LayoutAnalyzer(debug=debug)
        if mangle_pat:
            analyzer.set_encoder(mangle_pat)

        feeder = PageFeeder(analyzer, linkinfo=linkinfo, acldb=None,
                                default_charset=default_charset, debug=debug)

        items = []
        for item in previous:
            content = self.getHtml(item)
            if self.disable or not self.condition(item):
                yield item
            elif item.get('_template'):
                yield item
            elif content is not None:
                feeder.feed_page(item['_site_url'] + item['_path'], content)
                items.append(item)
            else:
                yield item
            feeder.close()
        if items:
            self.clusters = {}
            clusters = analyzer.analyze(cluster_threshold, title_threshold)
            patternset = LayoutPatternSet()
            patternset.pats = [c for c in clusters if c.pattern and score_threshold <= c.score]

        #default_charset='iso-8859-1'
        pat_threshold=0.8
        self.debug = 0
        strict=True
        for item in items:
            content = self.getHtml(item)
            name = item['_site_url'] + item['_path']
            if name == 'linkinfo': continue
            tree = parse(content, charset=default_charset)
            (pat1, layout) = patternset.identify_layout(tree, pat_threshold, strict=strict)
            etree = lxml.html.fromstring(content)
            newfields = self.dump_text(name, pat1, layout, etree, item['_path'])
            if newfields:
                self.log.info("PASS: '%s', matched=%s", item.get('_path'), newfields.keys() )
            else:
                self.log.info("FAIL: '%s'", item.get('_path'))
                
            item.update( newfields )
            yield item


    def getHtml(self, item):
              path = item.get('_path', None)
              content = item.get('_content', None) or item.get('text', None)
              mimetype = item.get('_mimetype', None)
              if  path is not None and \
                    content is not None and \
                    mimetype in ['text/xhtml', 'text/html']:
                  return content
              else:
                  return None

    def dump_text(self, name, pat1, layout, tree, path):
        codec_out='utf-8'
        diffscore_threshold=0.5
        main_threshold=50

        item = {}

        enc = lambda x: x.encode(codec_out, 'replace')
        if not layout:
          return {}
        
        if self.debug:
            for sect in layout:
                self.log.debug( 'DEBUG: SECT-%d: diffscore=%.2f' % (sect.id, sect.diffscore) )
                for b in sect.blocks:
                    self.log.debug( '   %s' % enc(b.orig_text) )

        xpaths = {}
        parts = []
        for sectno in xrange(len(layout)):
          sect = layout[sectno]
          field = None
          if sectno == pat1.title_sectno:
            field = 'title'
            for b in sect.blocks:
              title = enc(b.orig_text)
              field = 'title'
              parts.append(('TITLE',title) )

          elif diffscore_threshold <= sect.diffscore:
            if pat1.title_sectno < sectno and main_threshold <= sect.mainscore:
              field = 'text'
              for b in sect.blocks:
                parts.append(('MAIN-%d'%sect.id, enc(b.orig_text)) )
            else:
              field = 'text'
              for b in sect.blocks:
                parts.append(('SUB-%d'%sect.id, enc(b.orig_text)) )

          if field:
              xpath = toXPath(sect.path)
              xpaths.setdefault(field,[]).append(xpath)
              for node in tree.xpath(xpath, namespaces=ns):
                    item.setdefault(field,'')
                    method = field == 'title' and 'text' or 'html'
                    item[field] += etree.tostring(node, method=method, encoding=unicode) + ' '
                    if method == 'html':
                      #so lxml from_fragment won't freak out
                      item[field] = '<div>%s</div>'% item[field]

        if parts:
            m = lambda field: field == 'title' and 'text' or 'html'
            templates = '\n\t'.join(["%s= %s %s"%(field, m(field), '\n\t'.join(xp)) for field,xp in xpaths.items()])
            text = '\n\t'.join(["%s: %s"%v for v in parts])            
            self.log.debug("'%s' discovered rules by clustering on '%s'\nRules:\n\t%s\nText:\n\t%s",
                           path, pat1.name, templates, text )


        return item


def nonoverlap(unique, new):
    """ return the elements which aren't descentants of each other """
    for format,e1 in new:
        #if e1 is an ascendant then replace
        add = True
        for f,e in unique:
            if e1 in [n for n in e.iterancestors()]:
                unique.remove((f,e))
        #if e1 is an descendant don't use it
            if e in [n for n in e1.iterancestors()]:
                add = False
                break
        if add:
            unique.append((format,e1))
    return unique


