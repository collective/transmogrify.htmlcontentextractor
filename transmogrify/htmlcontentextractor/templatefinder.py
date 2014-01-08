import re
from zope.interface import classProvides
from zope.interface import implements
from collective.transmogrifier.interfaces import ISectionBlueprint
from collective.transmogrifier.interfaces import ISection
from lxml import etree
import lxml.html
import lxml.html.soupparser
import lxml.etree
from collective.transmogrifier.utils import Expression
import datetime
try:
    from collections import OrderedDict
except ImportError:
    # python 2.6 or earlier, use backport
    from ordereddict import OrderedDict
import logging
import urlparse

"""
transmogrify.htmlcontentextractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This blueprint extracts out title, description and body from html
either via xpath, TAL. This blueprint can either extract fields from a single item, or the item
could represent a list of data about items linked on different pages.


For example ::

  [template1]
  blueprint = transmogrify.htmlcontentextractor
  rules =
      title       = //div[@class='body']//h1[1]/text()
      description = //div[contains(@class,'admonition-description')]//p[@class='last']/text()
      text        = //div[@class='body']
      _delete1    = optional //div[@class='body']//a[@class='headerlink']
      _delete2    = optional //div[contains(@class,'admonition-description')]
  html-key = text

To help debug your template rules you can set debug mode.

For more information about XPath see

- http://www.w3schools.com/xpath/default.asp
- http://blog.browsermob.com/2009/04/test-your-selenium-xpath-easily-with-firebug/


Options:

:rules:
  Newline separated list of rules either
  'field = XPATH, or 'field = optional XPATH'. Each XPATH must match unless the 'optional' keyword is
  used. Each XPATH removes it's selected nodes from the html and no two XPATHs can select
  the same html node.

:tal:
  Newline separated list of tal expressions of the form 'field = TAL_EXPRESSION'. These act after the
  the xpaths have been evaluated and have access to any html the xpaths have extracted.

:html-key:
  The field key which contains the html to extract from

:remainder-key:
  The field to set with html left after all the XPATH selected nodes have been removed. Defauls to '_template'.

:repeat:
  Extract metadata about content linked to it a list on a page. Repeat is an XPATH
  where each other XPATH is relative to. To use repeat you need to also specify a 'url'.

:url:
  a XPATH which selects a href which links to the item. Any fields matched will
  be associated with the item linked rather than the current page. Must be used
  with 'repeat'.


:act_as_filter:
  .default 'No'. If 'True', any content extracted will be applied to items even if they had previously
  matched another templatefinder blueprint before this one. Determining if a previous template has already matched is
  done by checking the existances of the '_template' field which is set on a successful match with the remaining html.

:generate_missing:
  default 'No'. When using `_apply_to_paths` and the item refered to by the link doesn't yet exist, create it. Generally
  this should not be the case as the whole site will be crawled.


"""


ns = {'re': "http://exslt.org/regular-expressions"}
attr = re.compile(r':(?P<attr>[^/:]*)=(?P<val>[^/:]*)')


def toXPath(pat):
    #td:valign=top/p:class=msonormal/span
    pat = attr.sub(r'[re:test(@\g<attr>,"^\g<val>$","i")]', pat)
    pat = pat.replace('/', '//')
    return "//" + pat

default_charset = 'utf-8'

NOTSET = object()

class TemplateFinder(object):
    classProvides(ISectionBlueprint)
    implements(ISection)

    def __init__(self, transmogrifier, name, options, previous):
        self.previous = previous
        self.groups = {}
        self.name = name
        self.logger = logging.getLogger(name)
        def best(keys, default):
            for n in keys:
                if n in options:
                    return options[n].strip()
            return default
        self.repeat = best(['repeat', 'match', '_match'], '/')
        self.url = best(['url', 'apply_to_paths', '_apply_to_paths'], '')

        self.act_as_filter = best(['act_as_filter', '_act_as_filter'], "No")
        self.act_as_filter = self.act_as_filter.lower() in ('yes', 'true')
        self.generate_missing = options.get('_generate_missing',
                                            options.get('_generate_missing', "No")).lower() in ('yes', 'true')

        self.text_key = options.get('html-key', 'text').strip()
        self.template_key = options.get('remainder-key', '_template').strip()

        rules = options.get('rules','')
        if rules:
            rules = [[v.strip() for v in line.split('=',1)]
                     for line in rules.split('\n') if line.strip()]
        else:
            # backwards compatibility
            order = options.get('_order', '').split()
            def specialkey(key):
                if key in ['blueprint', 'debug', '_order', '_match',
                    '_apply_to_paths', '_apply_to_paths_prefix', '_act_as_filter',
                    '_generate_missing', 'html-key', 'remainder-key']:
                    return True
                if key in order:
                    return True
                if key.startswith('@'):
                    return True
                return False
            keys = order + [k for k in options.keys() if not specialkey(k)]
            rules = [(key, options[key]) for key in keys]

        for key,value in rules:
            try:
                group, field = key.split('-', 1)
                group = int(group)
            except:
                group, field = '1', key
            xps = []
            res = re.findall("(?m)^(text|html|optional|delete|tal|optionaltext|optionalhtml)\s(.*)$", value)
            if not res:
                format, value = 'html', value
            else:
                format, value = res[0]
            for line in value.strip().split('\n'):
                xp = line.strip()
                if format.lower() == 'tal':
                    xp = Expression(xp, transmogrifier, name, options, datetime=datetime)
                xps.append((format, xp))
            group = self.groups.setdefault(group, OrderedDict())
            group[field] = xps

        self.tal = []
        tal = options.get('tal','')
        if tal:
            tal = [[v.strip() for v in line.split('=',1)]
                     for line in tal.split('\n') if line.strip()]
            for key,rule in tal:
                self.tal.append(( key, Expression(rule, transmogrifier, name, options, datetime=datetime)))



    def __iter__(self):
        site_items = []
        site_items_lookup = {}
        if self.repeat:
            # In this case we need all items to be processed first so
            # we can match any urls we find to the existing item and merge
            for item in self.previous:
                site_items.append(item)
                if '_path' in item:
                    site_items_lookup[item['_site_url']+item['_path']] = item
        else:
            site_items = self.previous

        notextracted = []
        total = 0
        skipped = 0
        alreadymatched = 0
        stats = {}
        for item in site_items:
            #import pdb; pdb.set_trace()
            total += 1
            content = self.getHtml(item)
            path = item.get('_path', '')
            if content is None:
                #log.warning('(%s) content is None'%item['_path'])
                skipped += 1
                if path:
                    self.logger.debug("SKIP: %s (no html)" % (path))
                yield item
                continue
            if not self.act_as_filter and self.template_key in item:
                # don't apply the template if another has already been applied
                alreadymatched += 1
                self.logger.debug("SKIP: %s (already extracted)" % (item['_path']))
                yield item
                continue
            base = item['_site_url']+item['_path']
            tree = lxml.html.fromstring(content)
            if self.repeat:
                repeated = tree.xpath(self.repeat, namespaces=ns)
            else:
                repeated = [tree]

            gotit = False
            for fragment in repeated:
                # get each target_item in the path selection and process with fragment_content
                if self.repeat:
                    target_url = None
                    for target_url in fragment.xpath(self.url, namespaces=ns):
                        target_url = urlparse.urljoin(base, target_url.strip("/"))
                        if target_url in site_items_lookup:
                            target_item = site_items_lookup[target_url]
                            break
                else:
                    target_item = item
                path = target_item['_path']

                # try each group in turn to see if they work
                for groupname in sorted(self.groups.keys()):
                    group = self.groups[groupname]
                    #TODO: before we reset the tree for each group attempt
                    # we could copy the document each time?, or else
                    # perhaps a group should be applied to all repeats first?
                    # the problem is that extract removes parts from the document
                    # probably should make extract keep tree intact unless it matches.
                    #tree = lxml.html.fromstring(content)

                    if group.get('path', path) == path and \
                            self.extract(group, fragment, target_item, stats):
                        gotit = True
                        break
                if not gotit:
                    #one of the repeats didn't match so we stop processing item
                    break

            if not gotit:
                notextracted.append(item)
            yield item

        self.logger.info("extracted %d/%d/%d/%d %s" % (total - len(notextracted) - alreadymatched - skipped,
                                                       total - alreadymatched - skipped,
                                                       total - skipped,
                                                       total, stats))

    def extract(self, pats, tree, item, stats):
        unique = OrderedDict()
        nomatch = []
        optional = []
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
                        format = format.lower()[:-4] + 'text'
                    elif format.lower().startswith('optional'):
                        format = 'optionaltext'
                nodes = tree.xpath(xp, namespaces=ns)
                if not nodes:
                    if format.lower().startswith('optional'):
                        optional.append((field, xp))
                    else:
                        nomatch.append((field, xp))
                        self.logger.debug("FAIL %s:%s=%s %s\n%s" % (item['_path'],
                                                        field, format, xp,
                                                        etree.tostring(tree, method='html', encoding=unicode)))
                        continue

                nodes = [(format, n) for n in nodes]
                unique[field] = nonoverlap(unique.setdefault(field, []), nodes)
        if nomatch:
            matched = [field for field in unique.keys()]
            unmatched = [field for field, xp in nomatch]
            self.logger.info("FAIL: '%s' matched=%s, unmatched=%s" % (item['_path'],
                                                             matched, unmatched))
            return False
        extracted = {}
        assert unique
        # we will pull selected nodes out of tree so data isn't repeated

        for field, nodes in unique.items():
            toremove = []
            for format, node in nodes:
                if getattr(node, 'drop_tree', None) is None:
                    continue
                if not node.getparent():
                    # already dropped
                    toremove.append((format, node))
                    continue
                try:
                    node.drop_tree()
                except:
                    self.logger.error("error in drop_tree %s=%s" % (field, etree.tostring(node, method='html', encoding=unicode)))
            for node in toremove:
                nodes.remove(node)

        for field, nodes in unique.items():
            for format, node in nodes:
                extracted.setdefault(field, '')
                format = format.lower().replace('optional', '')
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
                value = tal(item, re=re)
                extracted[field] = extracted.get(field, '') + value
        for field, tal in self.tal:
            value = tal(item, re=re)
            extracted[field] = value
        item.update(extracted)

        unmatched = set([field for field, xp in optional])
        matched = set(unique.keys()) - set(unmatched)
        for field in matched:
            stats[field] = stats.get(field, 0) + 1
        self.logger.info("PASS: '%s' matched=%s, unmatched=%s", item['_path'], list(matched), list(unmatched))
        if '_tree' in item:
            del item['_tree']
        if not self.act_as_filter:
            item[self.template_key] = etree.tostring(tree, method='html', encoding=unicode)

        return item

    def getHtml(self, item):
        """Return the right html content based on attribute and mimetype"""
        path = item.get('_path', None)
        content = item.get(self.text_key, None)
#        mimetype = item.get('_mimetype', None)
        if path is not None and \
           content is not None:
#           mimetype in ['text/xhtml', 'text/html']:
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
    """Return the elements which aren't descentants of each other"""
    for format, e1 in new:
        #if e1 is an ascendant then replace
        add = True
        toremove = []
        for f, e in unique:
            if e1 == e:
                toremove.append((f, e))
            elif e1 in set(ancestors(e)):
                toremove.append((f, e))
            elif e in set(ancestors(e1)):
                add = False
                break
        if add:
            unique.append((format, e1))
        for pair in toremove:
            unique.remove(pair)
    return unique


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
