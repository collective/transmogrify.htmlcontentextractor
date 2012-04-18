Introduction
============

Helpful transmogrifier blueprints to extract text or html out of html content.


transmogrify.htmlcontentextractor.auto
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This blueprint has a clustering algorithm that tries to automatically extract the content from the HTML template.
This is slow and not always effective. Often you will need to input your own template extraction rules.
In addition to extracting Title, Description and Text of items the blueprint will output
the rules it generates to a logger with the same name as the blueprint.

Setting debug mode on templateauto will give you details about the rules it uses. ::

  ...
  DEBUG:templateauto:'icft.html' discovered rules by clustering on 'http://...'
  Rules:
	text= html //div[@id = "dal_content"]//div[@class = "content"]//p
	title= text //div[@id = "dal_content"]//div[@class = "content"]//h3
  Text:
	TITLE: ...
	MAIN-10: ...
	MAIN-10: ...
	MAIN-10: ...

Options
-------

condition
  TAL Expression to control use of this blueprint

debug
  default is ''

transmogrify.htmlcontentextractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This blueprint extracts out title, description and body from html
either via xpath, TAL or by automatic cluster analysis


Rules are in the form of ::

  (title|description|text|anything) = (text|html|optional|tal) Expression

Where expression is either TAL or XPath

For example ::

  [template1]
  blueprint = transmogrify.htmlcontentextractor
  title       = text //div[@class='body']//h1[1]
  _delete1    = optional //div[@class='body']//a[@class='headerlink']
  _delete2    = optional //div[contains(@class,'admonition-description')]
  description = text //div[contains(@class,'admonition-description')]//p[@class='last']
  text        = html //div[@class='body']

Note that for a single template e.g. template1, ALL of the XPaths need to match otherwise
that template will be skipped and the next template tried. If you'd like to make it
so that a single XPath isn't nessary for the template to match then use the keyword `optional` or `optionaltext`
instead of `text` or `html` before the XPath.


When an XPath is applied within a single template, the HTML it matches will be removed from the page.
Another rule in that same template can't match the same HTML fragment.

If a content part is not useful (e.g. redundant text, title or description) it is a way to effectively remove that HTML
from the content.

To help debug your template rules you can set debug mode.


For more information about XPath see

- http://www.w3schools.com/xpath/default.asp
- http://blog.browsermob.com/2009/04/test-your-selenium-xpath-easily-with-firebug/
