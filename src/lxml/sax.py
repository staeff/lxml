"""
SAX-based adapter to copy trees from/to the Python standard library.

Use the `ElementTreeContentHandler` class to build an ElementTree from
SAX events.

Use the `ElementTreeProducer` class or the `saxify()` function to fire
the SAX events of an ElementTree against a SAX ContentHandler.

See http://codespeak.net/lxml/sax.html
"""

from __future__ import absolute_import

from xml.sax.handler import ContentHandler
from lxml import etree
from lxml.etree import ElementTree, SubElement
from lxml.etree import Comment, ProcessingInstruction


class SaxError(etree.LxmlError):
    """General SAX error.
    """


def _getNsTag(tag):
    if tag[0] == '{':
        return tuple(tag[1:].split('}', 1))
    else:
        return None, tag


class ElementTreeContentHandler(ContentHandler):
    """Build an lxml ElementTree from SAX events.
    """
    def __init__(self, makeelement=None):
        ContentHandler.__init__(self)
        self._root = None
        self._root_siblings = []
        self._element_stack = []
        self._default_ns = None
        self._ns_mapping = { None : [None] }
        self._new_mappings = {}
        if makeelement is None:
            makeelement = etree.Element
        self._makeelement = makeelement

    def _get_etree(self):
        "Contains the generated ElementTree after parsing is finished."
        return ElementTree(self._root)

    etree = property(_get_etree, doc=_get_etree.__doc__)

    def setDocumentLocator(self, locator):
        pass

    def startDocument(self):
        pass

    def endDocument(self):
        pass

    def startPrefixMapping(self, prefix, uri):
        self._new_mappings[prefix] = uri
        try:
            self._ns_mapping[prefix].append(uri)
        except KeyError:
            self._ns_mapping[prefix] = [uri]
        if prefix is None:
            self._default_ns = uri

    def endPrefixMapping(self, prefix):
        ns_uri_list = self._ns_mapping[prefix]
        ns_uri_list.pop()
        if prefix is None:
            self._default_ns = ns_uri_list[-1]

    def _buildTag(self, ns_name_tuple):
        ns_uri, local_name = ns_name_tuple
        if ns_uri:
            el_tag = "{%s}%s" % ns_name_tuple
        elif self._default_ns:
            el_tag = "{%s}%s" % (self._default_ns, local_name)
        else:
            el_tag = local_name
        return el_tag

    def startElementNS(self, ns_name, qname, attributes=None):
        el_name = self._buildTag(ns_name)
        if attributes:
            attrs = {}
            try:
                iter_attributes = attributes.iteritems()
            except AttributeError:
                iter_attributes = attributes.items()

            for name_tuple, value in iter_attributes:
                if name_tuple[0]:
                    attr_name = "{%s}%s" % name_tuple
                else:
                    attr_name = name_tuple[1]
                attrs[attr_name] = value
        else:
            attrs = None

        element_stack = self._element_stack
        if self._root is None:
            element = self._root = \
                      self._makeelement(el_name, attrs, self._new_mappings)
            if self._root_siblings and hasattr(element, 'addprevious'):
                for sibling in self._root_siblings:
                    element.addprevious(sibling)
            del self._root_siblings[:]
        else:
            element = SubElement(element_stack[-1], el_name,
                                 attrs, self._new_mappings)
        element_stack.append(element)

        self._new_mappings.clear()

    def processingInstruction(self, target, data):
        pi = ProcessingInstruction(target, data)
        if self._root is None:
            self._root_siblings.append(pi)
        else:
            self._element_stack[-1].append(pi)

    def endElementNS(self, ns_name, qname):
        element = self._element_stack.pop()
        el_tag = self._buildTag(ns_name)
        if el_tag != element.tag:
            raise SaxError("Unexpected element closed: " + el_tag)

    def startElement(self, name, attributes=None):
        if attributes:
            attributes = dict(
                    [((None, k), v) for k, v in attributes.items()]
                )
        self.startElementNS((None, name), name, attributes)

    def endElement(self, name):
        self.endElementNS((None, name), name)

    def characters(self, data):
        last_element = self._element_stack[-1]
        try:
            # if there already is a child element, we must append to its tail
            last_element = last_element[-1]
            last_element.tail = (last_element.tail or '') + data
        except IndexError:
            # otherwise: append to the text
            last_element.text = (last_element.text or '') + data

    ignorableWhitespace = characters


class ElementTreeProducer(object):
    """Produces SAX events for an element and children.
    """
    def __init__(self, element_or_tree, content_handler):
        try:
            element = element_or_tree.getroot()
        except AttributeError:
            element = element_or_tree
        self._element = element
        self._content_handler = content_handler
        from xml.sax.xmlreader import AttributesNSImpl as attr_class
        self._attr_class = attr_class
        self._empty_attributes = attr_class({}, {})

    def saxify(self):
        self._content_handler.startDocument()

        element = self._element
        if hasattr(element, 'getprevious'):
            siblings = []
            sibling = element.getprevious()
            while getattr(sibling, 'tag', None) is ProcessingInstruction:
                siblings.append(sibling)
                sibling = sibling.getprevious()
            for sibling in siblings[::-1]:
                self._recursive_saxify(sibling)

        self._recursive_saxify(element)

        if hasattr(element, 'getnext'):
            sibling = element.getnext()
            while getattr(sibling, 'tag', None) is ProcessingInstruction:
                self._recursive_saxify(sibling)
                sibling = sibling.getnext()

        self._content_handler.endDocument()

    def _recursive_saxify(self, element):
        content_handler = self._content_handler
        tag = element.tag
        if tag is Comment or tag is ProcessingInstruction:
            if tag is ProcessingInstruction:
                content_handler.processingInstruction(
                    element.target, element.text)
            if element.tail:
                content_handler.characters(element.tail)
            return

        # Get a new copy in this call, so changes don't propagate upwards
        new_prefixes = []
        parent_nsmap = getattr(element.getparent(), 'nsmap', {})
        if element.nsmap != parent_nsmap:
            # There has been updates to the namespace
            for prefix, ns_uri in element.nsmap.items():
                if parent_nsmap.get(prefix) != ns_uri:
                    new_prefixes.append( (prefix, ns_uri) )

        build_qname = self._build_qname
        attribs = element.items()
        if attribs:
            attr_values = {}
            attr_qnames = {}
            for attr_ns_name, value in attribs:
                attr_ns_tuple = _getNsTag(attr_ns_name)
                attr_values[attr_ns_tuple] = value
                attr_qnames[attr_ns_tuple] = build_qname(
                    attr_ns_tuple[0], attr_ns_tuple[1], element.nsmap, -1)
            sax_attributes = self._attr_class(attr_values, attr_qnames)
        else:
            sax_attributes = self._empty_attributes

        ns_uri, local_name = _getNsTag(tag)
        qname = build_qname(ns_uri, local_name, element.nsmap, element.prefix)

        for prefix, uri in new_prefixes:
            content_handler.startPrefixMapping(prefix, uri)
        content_handler.startElementNS((ns_uri, local_name),
                                       qname, sax_attributes)
        if element.text:
            content_handler.characters(element.text)
        for child in element:
            self._recursive_saxify(child)
        content_handler.endElementNS((ns_uri, local_name), qname)
        for prefix, uri in new_prefixes:
            content_handler.endPrefixMapping(prefix)
        if element.tail:
            content_handler.characters(element.tail)

    def _build_qname(self, ns_uri, local_name, prefixes, preferred_prefix):
        if ns_uri is None:
            return local_name

        if prefixes.get(preferred_prefix) == ns_uri:
            prefix = preferred_prefix
        else:
            # Pick the first matching prefix:
            for pfx in sorted(prefixes, key=str):
                if prefixes[pfx] == ns_uri:
                    prefix = pfx
                    if pfx is None and preferred_prefix == -1:
                        # If preferred_prefix is -1, that's a flag to say
                        # that we want a prefix, any prefix, and only
                        # accept the default prefix if no other is
                        # available
                        continue
                    break

        if prefix is None:
            # Default namespace
            return local_name
        return prefix + ':' + local_name

def saxify(element_or_tree, content_handler):
    """One-shot helper to generate SAX events from an XML tree and fire
    them against a SAX ContentHandler.
    """
    return ElementTreeProducer(element_or_tree, content_handler).saxify()
