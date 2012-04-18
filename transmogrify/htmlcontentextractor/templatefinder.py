
import fnmatch
from zope.interface import classProvides
from zope.interface import implements
from collective.transmogrifier.interfaces import ISectionBlueprint
from collective.transmogrifier.interfaces import ISection
from collective.transmogrifier.utils import Matcher

from webstemmer.analyze import PageFeeder, LayoutAnalyzer, LayoutCluster
from webstemmer.extract import TextExtractor, LayoutPatternSet, LayoutPattern
from webstemmer.layoutils import sigchars, get_textblocks, retrieve_blocks, WEBSTEMMER_VERSION, KEY_ATTRS
from webstemmer.zipdb import ACLDB
from webstemmer.htmldom import parse
from lxml import etree
import lxml.html
import lxml.html.soupparser
import lxml.etree
from collective.transmogrifier.utils import Expression
import datetime

from StringIO import StringIO
from sys import stderr

import logging



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
attr = re.compile(r':(?P<attr>[^/:]*)=(?P<val>[^/:]*)')
def toXPath(pat):
    #td:valign=top/p:class=msonormal/span
    pat = attr.sub(r'[re:test(@\g<attr>,"^\g<val>$","i")]', pat)
    pat = pat.replace('/', '//')
    return "//" + pat


default_charset='utf-8'

class TemplateFinder(object):
    classProvides(ISectionBlueprint)
    implements(ISection)

    """ Template finder will associate groups take groups of xpaths and try to extract
    field information using them. If any xpath fails for a given group then none of the
    extracted text in that group is used and the next xpath is tried. The last group to
    be tried is an automatic group made up of xpaths analysed by clustering the pages
    Format for options is

    1-content = text //div
    2-content = html //div
    1-title = text //h1
    2-title = html //h2
    """



    def __init__(self, transmogrifier, name, options, previous):
        self.previous = previous
        self.groups = {}
        self.name = name
        self.logger = logging.getLogger(name)

        for key, value in options.items():
            if key in ['blueprint','debug'] or key.startswith('@'):
                continue
            try:
                group, field = key.split('-', 1)
                group = int(group)
            except:
                group, field = '1',key
            xps = []
            res = re.findall("(?m)^(text|html|optional|delete|tal|optionaltext|optionalhtml)\s(.*)$", value)
            if not res:
                format,value = 'html',value           
            else:
                format,value = res[0]
            for line in value.strip().split('\n'):
                xp = line.strip()
                if format.lower() == 'tal':
                    xp = Expression(xp, transmogrifier, name, options, datetime=datetime)
                xps.append((format,xp))
            group = self.groups.setdefault(group, {})
            group[field] = xps



    def __iter__(self):
        notextracted = []
        total = 0
        skipped = 0
        for item in self.previous:
            total += 1
            content = self.getHtml(item)
            path = item.get('_path','')
            if content is None:
                #log.warning('(%s) content is None'%item['_path'])
                skipped += 1
                if path:
                    self.logger.debug("SKIP: %s (no html)"%(path))
                yield item
                continue
            path = item['_site_url'] + item['_path']

            # try each group in turn to see if they work
            gotit = False
            for groupname in sorted(self.groups.keys()):
                group = self.groups[groupname]
                tree = lxml.html.fromstring(content)
                if group.get('path', path) == path and self.extract(group, tree, item):
                    gotit = True
                    break
            if gotit:
                yield item
            else:
                notextracted.append(item)
        for item in notextracted:
            yield item
        self.logger.info("extracted %d/%d/%d"%(total-len(notextracted)-skipped,
                                               total-skipped,
                                               total))


    def extract(self, pats, tree, item):
        unique = {}
        nomatch = []
        optional = []
        if '_template' in item:
            # don't apply the template if another has already been applied
            self.logger.debug("SKIP: %s (already extracted)"%(item['_path']))
            return
        for field, xps in pats.items():
            if field == 'path':
                continue
            for format, xp in xps:
                if format.lower() == 'tal':
                    continue
                if xp.strip().lower().endswith('/text()'):
                    #treat special so normal node ops still work
                    xp = xp.strip()[:-7]
                    if format.lower().endswith('html'):
                        format = format.lower()[:-4]+'text'
                    elif format.lower().startswith('optional'):
                        format = 'optionaltext'
                nodes = tree.xpath(xp, namespaces=ns)
                if not nodes:
                    if format.lower().startswith('optional'):
                        optional.append( (field, xp))
                    else:
                        nomatch.append( (field,xp) )
                        self.logger.debug("FAIL %s:%s=%s %s\n%s"%(item['_path'],
                                                        field, format, xp,
                                                        etree.tostring(tree, method='html', encoding=unicode)))
                        continue
                
                nodes = [(format, n) for n in nodes]
                unique[field] = nonoverlap(unique.setdefault(field,[]), nodes)
        if nomatch:
            matched = [field for field in unique.keys()]
            unmatched = [field for field, xp in nomatch]
            self.logger.info( "FAIL: '%s' matched=%s, unmatched=%s" % (item['_path'],
                                                             matched, unmatched) )
            return False
        extracted = {}
        assert unique
        # we will pull selected nodes out of tree so data isn't repeated

        for field, nodes in unique.items():
            for format, node in nodes:
                if getattr(node, 'drop_tree', None) is None:
                    continue
                if not node.getparent():
                    continue
                try:
                    node.drop_tree()
                except:
#                    import pdb; pdb.set_trace()
                    self.logger.error("error in drop_tree %s=%s"%(field,etree.tostring(node, method='html', encoding=unicode)))

        for field, nodes in unique.items():
            for format, node in nodes:
                extracted.setdefault(field,'')
                format = format.lower().replace('optional','')
                if format in ['delete']:
                    continue
                if not getattr(node, 'iterancestors', None):
                    extracted[field] = unicode(node)
                elif format in ['text']:
                    value = etree.tostring(node, method='text', encoding=unicode, with_tail=False)
                    if extracted[field]:
                        extracted[field] += ' ' + value
                    else:
                        extracted[field] += value
                else:
                    extracted[field] += etree.tostring(node, method='html', encoding=unicode)
        # What was this code for?
        #for field, nodes in unique.items():
        #    for format, node in nodes:
        #        html = extracted[field]
        #        try:
        #            lxml.html.fragment_fromstring(html)
        #        except lxml.etree.ParserError:
        #            extracted[field] = html
       
        item.update(extracted)

        #match tal format
        extracted = {}
        for field, xps in pats.items():
            if field == 'path':
                continue
            for format, tal in xps:
                if format.lower() != 'tal':
                    continue
                value = tal(item)
                extracted[field] = extracted.get(field, '') + value
        item.update(extracted)

        unmatched = set([field for field,xp in optional])
        matched = set(unique.keys()) - set(unmatched)
        self.logger.info( "PASS: '%s' matched=%s, unmatched=%s", item['_path'], list(matched) , list(unmatched))
        if '_tree' in item:
            del item['_tree']
        item['_template'] = None
        return item

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


def ancestors(e):
    if not getattr(e, 'iterancestors', None):
        yield e
        e = e.getparent()
    for n in e.iterancestors():
        yield n


def nonoverlap(unique, new):
    """ return the elements which aren't descentants of each other """
    for format,e1 in new:
        #if e1 is an ascendant then replace
        add = True
        toremove = []
        for f,e in unique:
            if e1 in set(ancestors(e)):
                toremove.append((f,e))
            if e in set(ancestors(e1)):
                add = False
                break
        if add:
            unique.append((format,e1))
        for pair in toremove:
            unique.remove(pair)
    return unique


