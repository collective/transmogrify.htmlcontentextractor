


class DiscoverAttributes (object):
    classProvides(ISectionBlueprint)
    implements(ISection)

    """ DiscoverAttributes will based on a matched XPath on the content process fragments of HTML
    through TemplateFinder searching for default values for attributes for a matched path value.
    The fragments are discarded and not considered content"""


    def __init__(self, transmogrifier, name, options, previous):
        self.previous = previous
        self.name = name
        self.logger = logging.getLogger(name)


       


    def __iter__ (self):

        site_items = []
        for item in self.previous:
            site_items.append(item)

        def iter_fragments (self):
            for frag in site_items:
                yield frag
        extractor = TemplateFinder(transmogrifier, "_discover_attributes_templatefinder", toptions, self.iter_fragments)

        default_attributes = {}
        for a in extractor:
            default_attributes[a["path"]] = a


        for item in site_items:
            if item["path"] in default_attributes:
                # set defaults

            yield item






                

         







