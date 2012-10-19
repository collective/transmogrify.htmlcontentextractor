import re
#import fnmatch
from zope.interface import classProvides
from zope.interface import implements
from collective.transmogrifier.interfaces import ISectionBlueprint
from collective.transmogrifier.interfaces import ISection
#from collective.transmogrifier.utils import Matcher

#from webstemmer.analyze import PageFeeder, LayoutAnalyzer, LayoutCluster
#from webstemmer.extract import TextExtractor, LayoutPatternSet, LayoutPattern
#from webstemmer.layoutils import sigchars, get_textblocks, retrieve_blocks, WEBSTEMMER_VERSION, KEY_ATTRS
#from webstemmer.zipdb import ACLDB
#from webstemmer.htmldom import parse
from lxml import etree
import lxml.html
import lxml.html.soupparser
import lxml.etree
from collective.transmogrifier.utils import Expression
import datetime
from collections import OrderedDict

#from StringIO import StringIO
#from sys import stderr

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

ns = {'re': "http://exslt.org/regular-expressions"}
attr = re.compile(r':(?P<attr>[^/:]*)=(?P<val>[^/:]*)')


def toXPath(pat):
    #td:valign=top/p:class=msonormal/span
    pat = attr.sub(r'[re:test(@\g<attr>,"^\g<val>$","i")]', pat)
    pat = pat.replace('/', '//')
    return "//" + pat

default_charset = 'utf-8'


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
        order = options.get('_order', '').split()
        self.match = options.get('_match', '/').strip()
        self.apply_to_paths = options.get('_apply_to_paths', '').strip()
        self.apply_to_paths_prefix = options.get('_apply_to_paths_prefix', '').strip("/")
        self.act_as_filter = options.get('_act_as_filter', "No").lower() in ('yes', 'true')
        self.generate_missing = options.get('_generate_missing', "No").lower() in ('yes', 'true')

        def specialkey(key):
            if key in ['blueprint', 'debug', '_order', '_match',
                '_apply_to_paths', '_apply_to_paths_prefix', '_act_as_filter', '_generate_missing']:
                return True
            if key in order:
                return True
            if key.startswith('@'):
                return True
            return False
        keys = order + [k for k in options.keys() if not specialkey(k)]

        for key in keys:
            value = options[key]
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

    def __iter__(self):
        iteration = self.attribute_to_item()
        if self.apply_to_paths:
            iteration = self.attribute_to_paths()
        return iteration

    def attribute_to_item(self):
        """Process items applying attributes to current item"""
        return self.process_items(self.previous)

    def attribute_to_paths(self):
        """Process items applying attributes to different item based on _apply_to_paths
           Optionally splitting content by _match
        """
        site_items = []
        site_items_lookup = {}
        #collected_pseudo_items = {}

        # read in all items
        for item in self.previous:
            site_items.append(item)
            site_items_lookup[item.get('_path')] = item

        # find fragments in items
        items_to_yield = []
        for item in site_items:
            items_to_yield.append(item)

            content = self.getHtml(item)
            if content is None:
                continue

            tree = lxml.html.fromstring(content)

            for fragment in tree.xpath(self.match, namespaces=ns):

                fragment_content = etree.tostring(fragment)
                fragment_tree = lxml.html.fromstring(fragment_content)

                # get each target_item in the path selection and process with fragment_content
                for target_path in fragment_tree.xpath(self.apply_to_paths, namespaces=ns):
                    # TODO: Better path normalization, eg: http://example.com/123.asp
                    target_path = target_path.strip("/")
                    if len(self.apply_to_paths_prefix) > 0:
                        target_path = self.apply_to_paths_prefix + "/" + target_path

                    if target_path not in site_items_lookup:
                        if self.generate_missing:
                            target_item = {
                                "_path": target_path,
                                "_site_url": item["_site_url"],
                                "_template_generated": True
                            }
                        else:
                            continue
                    else:
                        target_item = site_items_lookup[target_path]

                    # save _content, _mimetype and _template
                    NOTSET = object()
                    target_content = target_item.get("_content", NOTSET)
                    target_mimetype = target_item.get("_content", NOTSET)

                    # set to tempory values during process_items
                    target_item["_content"] = fragment_content
                    target_item["_mimetype"] = "text/html"
                    target_item["_metaitem"] = item

                    list(self.process_items([target_item]))

                    # reset to original values
                    target_item["_content"] = target_content
                    target_item["_mimetype"] = target_mimetype

                    for key in ["_content", "_mimetype"]:
                        if target_item[key] == NOTSET:
                            del target_item[key]

                    if target_item.get("_template_generated") and "_template" in target_item:
                        site_items_lookup[target_path] = target_item
                        items_to_yield.append(target_item)

        for item in items_to_yield:
            yield item

    def attribute_to_folders(self):
        """Process items applying attributes to different item based on _apply_to_folders
           Optionally splitting content by _match
        """
        import pdb; pdb.set_trace()
        site_items = []
        site_items_lookup = {}
        the_folder = self.apply_to_folders.rstrip("/").rsplit("/", 1)[0]

        # read in all items
        for item in self.previous:
            site_items.append(item)
            site_items_lookup[item.get('_path')] = item

        # find fragments in items
        for item in site_items:

            content = self.getHtml(item)
            if content is None:
                continue

            tree = lxml.html.fromstring(content)

            for fragment in tree.xpath(self.match, namespaces=ns):

                fragment_content = etree.tostring(fragment)
                fragment_tree = lxml.html.fromstring(fragment_content)

                # get each target_item in the path selection and process with fragment_content
                for target_path in fragment_tree.xpath(the_folder, namespaces=ns):
                    # TODO: Better path normalization, eg: http://example.com/123.asp
                    target_path = target_path.strip("/")

                    if target_path not in site_items_lookup:
                        # TODO: should implement an option to create new content
                        continue

                    target_item = site_items_lookup[target_path]

                    # save _content, _mimetype and _template
                    NOTSET = object()
                    target_content = target_item.get("_content", NOTSET)
                    target_mimetype = target_item.get("_content", NOTSET)

                    # set to tempory values during process_items
                    target_item["_content"] = fragment_content
                    target_item["_mimetype"] = "text/html"
                    target_item["_metaitem"] = item

                    list(self.process_items([target_item]))

                    # reset to original values
                    target_item["_content"] = target_content
                    target_item["_mimetype"] = target_mimetype

                    for key in ["_content", "_mimetype"]:
                        if target_item[key] == NOTSET:
                            del target_item[key]

        for item in site_items:
            yield item

    def process_items(self, items):
        """Process items from basic template"""
        notextracted = []
        total = 0
        skipped = 0
        alreadymatched = 0
        stats = {}
        for item in items:
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
            if not self.act_as_filter and '_template' in item:
                # don't apply the template if another has already been applied
                alreadymatched += 1
                self.logger.debug("SKIP: %s (already extracted)" % (item['_path']))
                yield item
                continue
            path = item['_site_url'] + item['_path']

            # try each group in turn to see if they work
            gotit = False
            for groupname in sorted(self.groups.keys()):
                group = self.groups[groupname]
                tree = lxml.html.fromstring(content)
                if group.get('path', path) == path and self.extract(group, tree, item, stats):
                    gotit = True
                    break
            if gotit:
                yield item
            else:
                notextracted.append(item)
                yield item
            #        for item in notextracted:
            #            yield item
        self.logger.info("extracted %d/%d/%d/%d %s" % (total - len(notextracted) - alreadymatched - skipped,
                                                       total - alreadymatched - skipped,
                                                       total - skipped,
                                                       total, stats))

    def extract(self, pats, tree, item, stats):
        unique = OrderedDict()
        nomatch = []
        optional = []
        #import pdb; pdb.set_trace()
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
        item.update(extracted)

        unmatched = set([field for field, xp in optional])
        matched = set(unique.keys()) - set(unmatched)
        for field in matched:
            stats[field] = stats.get(field, 0) + 1
        self.logger.info("PASS: '%s' matched=%s, unmatched=%s", item['_path'], list(matched), list(unmatched))
        if '_tree' in item:
            del item['_tree']
        if not self.act_as_filter:
            item['_template'] = None

        return item

    def getHtml(self, item):
        """Return the right html content based on attribute and mimetype"""
        path = item.get('_path', None)
        content = item.get('_content', None) or item.get('text', None)
        mimetype = item.get('_mimetype', None)
        if path is not None and \
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
