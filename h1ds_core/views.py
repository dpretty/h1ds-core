"""

TODO: most of the  response mixins do a check for  ndim etc, we should
be able to refactor code to remove duplication..
"""
import csv
import xml.etree.ElementTree as etree
import json
import time
import StringIO
import numpy as np
import hashlib
import pylab

from django.shortcuts import render_to_response, redirect, get_object_or_404
from django.template import RequestContext
from django.http import HttpResponse, StreamingHttpResponse, Http404
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django import forms
from django.views.generic import View, ListView, DetailView, RedirectView
from django.utils.decorators import method_decorator
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.conf import settings
from django.utils.importlib import import_module

from h1ds_core.models import UserSignal, UserSignalForm, Worksheet, Node, Shot
from h1ds_core.utils import get_backend_shot_manager
from h1ds_core.base import get_filter_list

backend_shot_manager = get_backend_shot_manager()

def get_shot_stream_generator():
    shotman = backend_shot_manager()
    def new_shot_generator():
        latest_shot = shotman.get_latest_shot()
        while True:
            time.sleep(1)
            tmp = shotman.get_latest_shot()
            if tmp != latest_shot:
                latest_shot = tmp
                yield "{}\n".format(latest_shot)
    return new_shot_generator
    
new_shot_generator = get_shot_stream_generator()

### TEMP ###
#import h1ds_core.filters
from h1ds_core.base import get_all_filters
############
all_filters = get_all_filters()

def get_format(request, default='html'):
    """get format URI query key.

    Fall back to 'view' for backwards compatability.

    """
    format_ =  request.GET.get('format', None)
    if not format_:
        format_ = request.GET.get('view', default)
    return format_

    
def homepage(request):
    """Return the H1DS homepage."""
    return render_to_response('h1ds_core/homepage.html', 
                              context_instance=RequestContext(request))

def logout_view(request):
    """Log the user out of H1DS."""
    logout(request)
    return redirect('/')
            

class ChangeProfileForm(forms.Form):
    help_text = ("Please use CamelCase, with each word capitalised. "
                 "For example: MarkOliphant or LymanSpitzer")
    username = forms.CharField(max_length=30, help_text=help_text)
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)
    email = forms.EmailField()


class UserMainView(ListView):

    def get_queryset(self):
        return Worksheet.objects.filter(user=self.request.user)

    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(UserMainView, self).dispatch(*args, **kwargs)

class WorksheetView(DetailView):

    def get_object(self):
        w = get_object_or_404(Worksheet,
                              user__username=self.kwargs['username'],
                              slug=self.kwargs['worksheet'])
        if w.is_public or w.user == self.request.user:
            return w
        else:
            raise PermissionDenied


@login_required
def edit_profile(request, username=''):
    if request.user.username == username:
        if request.method == 'POST':
            form = ChangeProfileForm(request.POST)
            if form.is_valid():
                u = User.objects.get(username=username)
                u.username = form.cleaned_data['username']
                u.first_name = form.cleaned_data['first_name']
                u.last_name = form.cleaned_data['last_name']
                u.email = form.cleaned_data['email']
                u.save()
                return redirect('/')
                
            else:
                data = {'username':username, 
                        'first_name':request.user.first_name,
                        'last_name':request.user.last_name,
                        'email':request.user.email}
                user_form = ChangeProfileForm(data)
                response_dict = {'form': user_form, 
                                 'return_url': '/user/profile/%s/' % username}
                return render_to_response('h1ds_core/userprofile.html', 
                                response_dict,
                                context_instance=RequestContext(request))
        else:
            data = {'username':username, 
                    'first_name':request.user.first_name,
                    'last_name':request.user.last_name,
                    'email':request.user.email}
            user_form = ChangeProfileForm(data)
            return render_to_response('h1ds_core/userprofile.html', 
                                      {'form':user_form},
                                      context_instance=RequestContext(request))
    else:
        return redirect('/')


def get_max_fid(request):
    # get maximum filter number
    filter_list = get_filter_list(request)
    if len(filter_list) == 0:
        max_filter_num = 0
    else:
        max_filter_num = max([i[0] for i in filter_list])
    return max_filter_num

class FilterBaseView(RedirectView):
    """Read in filter info from HTTP query and apply H1DS filter syntax.

    The request GET query must contain  a field named 'filter' which has
    the filter function  name as its value. Separate fields  for each of
    the filter arguments  are also required, where the  argument name is
    as it appears in the filter function code.

    If  overwrite_fid is  False,  the new  filter will  have  an FID  +1
    greater than the highest existing  filter. If overwrite_fid is True,
    we expect a query field with an fid to overwrite.
    
    TODO: Do  we really  need path  to be passed  explicitly as  a query
    field? or can we  use session info? - largest FID  is taken from the
    request, but we return url from path... can't be good.
    TODO: kwargs are not yet supported for filter functions.
    """
    
    http_method_name = ['get']

    def get_filter_url(self, overwrite_fid=False):
        # Get name of filter function
        qdict = self.request.GET.copy()
        filter_name = qdict.pop('filter')[-1]

        # Get the actual filter function
        #filter_function = getattr(df, filter_name)
        filter_class = all_filters[filter_name]
        
        # We'll append the filter to this path and redirect there.
        return_path = qdict.pop('path')[-1]

        if overwrite_fid:
            fid = int(qdict.pop('fid')[-1])
            for k, v in qdict.items():
                if k.startswith('f%d' %fid):
                    qdict.pop(k)
        else:
            # Find the maximum fid in the existing query and +1
            fid = get_max_fid(self.request)+1

        # We expect the filter arguments  to be passed as key&value in
        # the HTTP query.
        filter_arg_values = [qdict.pop(a)[-1] for a in filter_class.kwarg_names]

        # add new filter to query dict
        qdict.update({'f%d' %(fid):filter_name})
        for name, val in zip(filter_class.kwarg_names, filter_arg_values):
            qdict.update({'f%d_%s' %(fid, name): val})

        return '?'.join([return_path, qdict.urlencode()])

class ApplyFilterView(FilterBaseView):
    def get_redirect_url(self, **kwargs):
        return self.get_filter_url()

class UpdateFilterView(FilterBaseView):
    def get_redirect_url(self, **kwargs):
        return self.get_filter_url(overwrite_fid=True)

class RemoveFilterView(RedirectView):

    http_method_names = ['get']

    def get_redirect_url(self, **kwargs):
        qdict = self.request.GET.copy()
        filter_id = int(qdict.pop('fid')[-1])
        return_path = qdict.pop('path')[-1]
        new_filter_values = []
        for k, v in qdict.items():
            if k.startswith('f%d' %filter_id):
                qdict.pop(k)
        return '?'.join([return_path, qdict.urlencode()])




class UserSignalCreateView(CreateView):

    form_class = UserSignalForm

    def get_success_url(self):
        return self.request.POST.get('url', "/")

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.user = self.request.user
        self.object.ordering = 1 # TODO
        self.object.url = self.request.POST.get('url', "/")
        self.object.save()
        return super(UserSignalCreateView, self).form_valid(form)


class UserSignalUpdateView(UpdateView):
    model = UserSignal

    def get_success_url(self):
        return self.request.POST.get('redirect_url', "/")

    def get_context_data(self, **kwargs):
        context = super(UserSignalUpdateView, self).get_context_data(**kwargs)
        context['redirect_url'] = self.request.GET.get('redirect_url', "/")
        return context

class UserSignalDeleteView(DeleteView):
    model = UserSignal

    def get_success_url(self):
        return self.request.POST.get('url', "/")


        
class ShotStreamView(View):

    http_method_names = ['get']

    def get(self, request, *args, **kwargs):
        return StreamingHttpResponse(new_shot_generator())


class RequestShotView(RedirectView):
    """Redirect to shot, as requested by HTTP post."""

    http_method_names = ['post']

    def get_redirect_url(self, **kwargs):
        shot = self.request.POST['go_to_shot']
        input_path = self.request.POST['reqpath']
        split_path = input_path.split("/")
        split_path[2] = str(shot)
        new_path = "/".join(split_path)
        return new_path

class AJAXShotRequestURL(View):
    """Return URL modified for requested shot"""

    http_method_names = ['get']

    def get(self, request, *args, **kwargs):
        input_path = request.GET.get('input_path')
        shot = int(request.GET.get('shot'))
        url_processor = URLProcessor(url=input_path)
        url_processor.shot = shot
        new_url = url_processor.get_url()
        output_json = '{"new_url": "%s"}' % new_url
        return HttpResponse(output_json, 'application/javascript')

def xml_latest_shot(request):
    """Hack...

    TODO: Hack to get IDL client working again - this should be merged
    with other latest shot view

    """
    
    shot = str(get_latest_shot())
    # TODO - get URI from settings, don't hardwire h1svr
    response_xml = etree.Element('{http://h1svr.anu.edu.au/data}dataurlmap',
                    attrib={'{http://www.w3.org/XML/1998/namespace}lang': 'en'})
    
    shot_number = etree.SubElement(response_xml, 'shot_number', attrib={})
    shot_number.text = shot
    return HttpResponse(etree.tostring(response_xml),
                        mimetype='text/xml; charset=utf-8')

class AJAXLatestShotView(View):
    """Return latest shot."""
    
    http_method_names = ['get']

    def get(self, request, *args, **kwargs):
        format_ = get_format(request, default='json')
        if format_.lower() == 'xml':
            return xml_latest_shot(request)
        latest_shot = get_latest_shot()
        return HttpResponse('{"latest_shot":"%s"}' %latest_shot,
                            'application/javascript')

def request_url(request):
    """Return the URL for the requested parameters."""
    
    shot = request.GET['shot']
    path = request.GET['path']
    tree = request.GET['tree']

    xml_elmt = '{http://h1svr.anu.edu.au/}dataurlmap'
    lang_attr = {'{http://www.w3.org/XML/1998/namespace}lang': 'en'}
    url_xml = etree.Element(xml_elmt, attrib=lang_attr)
    
    shot_number = etree.SubElement(url_xml, 'shot_number', attrib={})
    shot_number.text = shot
    data_path = etree.SubElement(url_xml, 'path', attrib={})
    data_path.text = path
    data_tree = etree.SubElement(url_xml, 'tree', attrib={})
    data_tree.text = tree

    url_processor = URLProcessor(shot=int(shot), tree=tree, path=path)
    url = url_processor.get_url()
    url_el = etree.SubElement(url_xml, 'url', attrib={})
    url_el.text = url

    return HttpResponse(etree.tostring(url_xml),
                        mimetype='text/xml; charset=utf-8')



from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.renderers import JSONRenderer
from rest_framework.renderers import YAMLRenderer
from rest_framework.renderers import XMLRenderer
from rest_framework.generics import ListAPIView
from h1ds_core.serializers import NodeSerializer, ShotSerializer

class NodeView(APIView):

    renderer_classes = (TemplateHTMLRenderer, JSONRenderer, YAMLRenderer, XMLRenderer,)
    
    def get_object(self, shot, nodepath):
        """Get node object for request.

        TODO:  this  method  does  a   lookup  for  each  level  of  the
        tree. There  are probably more efficient  ways...
        Options (need to evaluate performace of each):
        1. We  could store the full  path in the Node  table (maybe ugly
        but faster?)
        2. Could use filter by tree  level and slug, and while there are
        more than 1 candidate nodes, track  back up the tree and compare
        parent nodes.
        
        """
        checksum = hashlib.sha1(nodepath).hexdigest()

        node = Node.objects.get(shot__number=shot, path_checksum=checksum)
        node.data = node.read_primary_data()
        node.apply_filters(self.request)
        return node
        
    def get(self, request, shot, nodepath, format=None):
        node = self.get_object(shot, nodepath)
        # TODO: yaml not working yet
        # TODO: format list shoudl be maintained elsewhere... probably in settings.
        node.get_alternative_format_urls(self.request, ["html", "json", "xml"]) 
        # apply filters here!?
        if request.accepted_renderer.format == 'html':
            if node.has_data == False:
                template = "node_without_data.html"
            else:
                template = "node_with_data.html"
            return Response({'node':node}, template_name='h1ds_core/'+template)
        serializer = NodeSerializer(node)
        return Response(serializer.data)
            

class ShotListView(ListAPIView):

    renderer_classes = (TemplateHTMLRenderer, JSONRenderer, YAMLRenderer, XMLRenderer,)
    # TODO: make this customisable.
    paginate_by = 25
    queryset = Shot.objects.all()
    serializer_class = ShotSerializer

    def get_template_names(self):
        return ("h1ds_core/shot_list.html", )

class ShotDetailView(APIView):
    renderer_classes = (TemplateHTMLRenderer, JSONRenderer, YAMLRenderer, XMLRenderer,)
    serializer_class = ShotSerializer
    
    def get_object(self):
        shot = Shot.objects.get(number=self.kwargs['shot'])
        return shot
        #qs = Node.objects.filter(level=0, shot=shot)
        #return qs

    def get_template_names(self):
        return ("h1ds_core/shot_detail.html", )

    def get(self, request, shot, format=None):
        shot = self.get_object()
        serializer = self.serializer_class(shot)
        return Response(serializer.data)
        
