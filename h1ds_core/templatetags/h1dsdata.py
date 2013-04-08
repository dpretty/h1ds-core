"""
Note, don't confuse  H1DS Data nodes with Django template  nodes. Try to
make each type obvious by their name.
"""
import inspect
from django import template
from django.core.urlresolvers import reverse
from django.utils.html import escape

register = template.Library()

class H1DSDataTemplateNode(template.Node):
    def __init__(self, node_name):
        self.node_var = template.Variable(node_name)
    def render(self, context):
        try:
            node = self.node_var.resolve(context)
            return '<div class="centrecontent"><div class="data">%s</div></div>' %(node.get_view('html'))
        except template.VariableDoesNotExist:
            return ''

def display_data(parser, token):
    try:
        # split_contents() knows not to split quoted strings.
        tag_name, data_name = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError, "%r tag requires a single argument" % token.contents.split()[0]
    return H1DSDataTemplateNode(data_name)


register.tag('display_data', display_data)

filter_html = """\
<div class="sidebarcontent">
 <form action="%(submit_url)s">
  <span class="left" title="%(text)s">%(clsname)s</span>
  <span class="right">%(input_str)s<input type="submit" title="add" value="+"/></span>
  <input type="hidden" name="filter" value="%(clsname)s">
  <input type="hidden" name="path" value="%(path)s">%(input_query)s
 </form>
</div>"""


active_filter_html ="""\
<div class="sidebarcontent">
 <form action="%(update_url)s">
  <span class="left" title="%(text)s">%(clsname)s</span>
  <span class="right">%(input_str)s
   <input type="hidden" name="fid" value="%(fid)s">
   <input title="update" type="submit" value="u"/>
  </span>
  <input type="hidden" name="filter" value="%(clsname)s">
  <input type="hidden" name="path" value="%(path)s">%(input_query)s
 </form>
 <span class="right">
  <form action="%(remove_url)s">
   <input type="hidden" name="path" value="%(path)s">
   <input type="hidden" name="fid" value="%(fid)s">
   <input title="remove" type="submit" value="-"/>%(existing_query)s
  </form>
 </span>
</div>
"""

def get_filter(context, filter_instance, is_active=False, fid=None, filter_data=None):
    try:
        request = context['request']
        existing_query_string = ''.join(['<input type="hidden" name="%s" value="%s" />' %(k,v) for k,v in request.GET.items()])
        arg_list = inspect.getargspec(filter_instance).args[1:]
        docstring = inspect.getdoc(filter_instance)
        if is_active:
            if filter_data == None:
                filter_data = []
            update_url = reverse("update-filter")
            remove_url = reverse("remove-filter")
            input_str = ''.join(['<input title="%(name)s" type="text" size=5 name="%(name)s" value="%(value)s">' %{'name':j,'value':filter_data[i]} for i,j in enumerate(arg_list)])

            return_string = active_filter_html %{
                'update_url':update_url,
                'text':docstring,
                'input_str':input_str,
                'clsname':filter_instance.__name__,
                'path':request.path,
                'input_query':existing_query_string,
                'fid':fid,
                'remove_url':remove_url,
                'existing_query':existing_query_string,
                }
            return return_string

        else:
            submit_url = reverse("apply-filter")
            input_str = ''.join(['<input title="%(name)s" type="text" size=5 name="%(name)s" placeholder="%(name)s">' %{'name':j} for j in arg_list])
            return_string =  filter_html %{'text':docstring,
                                           'input_str':input_str,
                                           'clsname':filter_instance.__name__,
                                           'submit_url':submit_url,
                                           'path':request.path,
                                           'input_query':existing_query_string}
            return return_string
    except template.VariableDoesNotExist:
        #return ''
        raise

@register.simple_tag(takes_context=True)
def show_filters(context, data_node):
    # TODO: HACK
    return ""#.join([get_filter(context, f) for f in data_node.data.available_filters])


@register.simple_tag(takes_context=True)
def show_active_filters(context, data_node):
    return "".join([get_filter(context, f, is_active=True, fid=fid, filter_data=fdata) for fid, f, fdata in data_node.data.filter_history])

@register.simple_tag(takes_context=True)
def show_info(context, data_node):
    # TODO
    return ""#"TODO... dtype: %s" % escape(str(type(data_node.data.data)))

@register.simple_tag(takes_context=True)
def get_url_for_shot(context, url, new_shot):
    #input_shot = shot_regex.findall(url)[0]
    print "temp hack - not working"
    return url#url.replace(str(input_shot), str(new_shot))


class H1DSViewNode(template.Node):
    def __init__(self, view_name):
        self.view_name_var = template.Variable(view_name)

    def render(self, context):
        try:
            view_name = self.view_name_var.resolve(context)
            request = context['request']
            qd_copy = request.GET.copy()
            qd_copy.update({'view': view_name})
            link_url = '?'.join([request.path, qd_copy.urlencode()])
            return '<a href="%s">%s</a>' %(link_url, view_name)
        except template.VariableDoesNotExist:
            return ''

def show_view(parser, token):
    try:
        # split_contents() knows not to split quoted strings.
        tag_name, view_name = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError, "%r tag requires a single argument" % token.contents.split()[0]
    return H1DSViewNode(view_name)

register.tag('show_view', show_view)


class GetAbsoluteUriNode(template.Node):
    def __init__(self):
        pass

    def render(self, context):
        try:
            request = context['request']
            return request.build_absolute_uri()

        except template.VariableDoesNotExist:
            return ''

def get_absolute_uri(parser, token):
    return GetAbsoluteUriNode()

register.tag('get_absolute_uri', get_absolute_uri)

